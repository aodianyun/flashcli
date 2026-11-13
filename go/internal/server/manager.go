package server

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/serveopts"
)

// ErrResourceExhausted indicates that loading another model would exceed the
// configured slot limit or available GPU memory.
var ErrResourceExhausted = errors.New("resource exhausted")

// ServeProcess is one `flashcli serve` child process.
type ServeProcess interface {
	Ref() string
	Endpoint() string
	PID() int
	Healthy(context.Context) error
	Running() bool
	// LastLog returns the tail of the child's log (empty when unavailable).
	LastLog() string
	Stop(context.Context) error
}

// Launcher starts a serve process for a bundle ref on a loopback port.
type Launcher interface {
	Start(context.Context, string, int) (ServeProcess, error)
}

// LoadOptions carries the per-model host, port and manifest serve flags.
type LoadOptions struct {
	Host  string
	Port  int
	Flags []string
}

// OptionLauncher is implemented by launchers that accept per-model options.
// The plain Launcher interface remains for tests and simple launchers.
type OptionLauncher interface {
	StartWithOptions(context.Context, string, LoadOptions) (ServeProcess, error)
}

// ManagerOptions controls model admission.
type ManagerOptions struct {
	// MaxLoaded is the maximum number of resident models. Zero means only the
	// GPU memory policy is enforced.
	MaxLoaded int
	// MinFreeVRAMMiB is the safety margin kept free on the GPU.
	MinFreeVRAMMiB int64
	// GPU returns the current GPU inventory. Nil falls back to gpu.Probe.
	GPU func(context.Context) ([]gpu.Device, error)
	// Inspect reads a bundle's admission metadata. Nil uses inspectBundle.
	Inspect func(string) (BundleInfo, error)
	// ServeSettings stores per-model host/port/serve options. Nil disables them.
	ServeSettings *serveSettingsStore
}

// Manager owns resident serve processes.
type Manager struct {
	mu        sync.Mutex
	instances map[string]*instance
	loading   map[string]chan struct{}
	launcher  Launcher
	opts      ManagerOptions
	pending   int
}

type instance struct {
	ref      string
	process  ServeProcess
	loadedAt time.Time
}

// NewManager creates a manager with a conservative single-model default.
func NewManager(l Launcher) *Manager {
	return NewManagerWithOptions(l, ManagerOptions{MaxLoaded: 1})
}

// NewManagerWithOptions creates a manager with explicit admission policy.
func NewManagerWithOptions(l Launcher, opts ManagerOptions) *Manager {
	return &Manager{
		instances: map[string]*instance{},
		loading:   map[string]chan struct{}{},
		launcher:  l,
		opts:      opts,
	}
}

// Load starts a serve process for ref if it is not already resident.
func (m *Manager) Load(ctx context.Context, refStr string) (*InstanceInfo, error) {
	return m.LoadWithProgress(ctx, refStr, nil)
}

// LoadWithProgress is Load with coarse progress events (bundle/weights/venv).
func (m *Manager) LoadWithProgress(ctx context.Context, refStr string, progress func(phase, message string)) (*InstanceInfo, error) {
	for {
		m.mu.Lock()
		if inst, ok := m.instances[refStr]; ok {
			info := infoFor(inst)
			m.mu.Unlock()
			return &info, nil
		}
		if wait, ok := m.loading[refStr]; ok {
			m.mu.Unlock()
			select {
			case <-wait:
				continue
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
		wait := make(chan struct{})
		m.loading[refStr] = wait
		m.mu.Unlock()

		info, err := m.load(ctx, refStr, progress)
		m.mu.Lock()
		delete(m.loading, refStr)
		close(wait)
		m.mu.Unlock()
		if err != nil {
			return nil, err
		}
		return &info, nil
	}
}

func (m *Manager) load(ctx context.Context, refStr string, progress func(phase, message string)) (InstanceInfo, error) {
	if m.launcher == nil {
		return InstanceInfo{}, errors.New("serve launcher is not configured")
	}
	if progress != nil && !ref.IsFlashHub(refStr) {
		progress("prepare", "preparing local bundle")
	}
	inspect := m.opts.Inspect
	if inspect == nil {
		inspect = inspectBundle
	}
	bundle, err := inspect(refStr)
	if err != nil {
		return InstanceInfo{}, err
	}
	if bundle.RunOnly {
		name := bundle.Name
		if name == "" {
			name = refStr
		}
		return InstanceInfo{}, fmt.Errorf("bundle %q is run-only (no serve entry); use `flashcli run %s`", name, refStr)
	}
	m.mu.Lock()
	if err := m.checkCapacityLocked(ctx, bundle); err != nil {
		m.mu.Unlock()
		return InstanceInfo{}, err
	}
	m.pending++
	m.mu.Unlock()
	defer func() {
		m.mu.Lock()
		m.pending--
		m.mu.Unlock()
	}()
	settings := ModelServeSettings{}
	if m.opts.ServeSettings != nil {
		settings = m.opts.ServeSettings.Get(refStr)
	}
	host := strings.TrimSpace(settings.Host)
	port := settings.Port
	if port > 0 {
		if !portAvailable(port) {
			return InstanceInfo{}, fmt.Errorf("serve port %d is already in use", port)
		}
	} else {
		var err error
		port, err = freePort()
		if err != nil {
			return InstanceInfo{}, err
		}
	}
	flags, err := serveopts.Flags(bundle.ServeOptions, settings.Options)
	if err != nil {
		return InstanceInfo{}, err
	}
	var proc ServeProcess
	if ol, ok := m.launcher.(OptionLauncher); ok {
		proc, err = ol.StartWithOptions(ctx, refStr, LoadOptions{Host: host, Port: port, Flags: flags})
	} else {
		proc, err = m.launcher.Start(ctx, refStr, port)
	}
	if err != nil {
		return InstanceInfo{}, err
	}
	deadline := time.Now().Add(120 * time.Second)
	lastLog := ""
	for {
		if progress != nil {
			if line := strings.TrimSpace(proc.LastLog()); line != "" && line != lastLog {
				lastLog = line
				progress("progress", line)
			}
		}
		if err := proc.Healthy(ctx); err == nil {
			break
		}
		// Return the child's own error instead of waiting out the deadline
		// (e.g. a run-only bundle rejects serve immediately).
		if !proc.Running() {
			_ = proc.Stop(context.Background())
			if detail := strings.TrimSpace(proc.LastLog()); detail != "" {
				return InstanceInfo{}, fmt.Errorf("serve process for %s exited: %s", refStr, detail)
			}
			return InstanceInfo{}, fmt.Errorf("serve process for %s exited before becoming ready", refStr)
		}
		if time.Now().After(deadline) {
			_ = proc.Stop(context.Background())
			return InstanceInfo{}, fmt.Errorf("serve process for %s did not become healthy", refStr)
		}
		select {
		case <-ctx.Done():
			_ = proc.Stop(context.Background())
			return InstanceInfo{}, ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
	inst := &instance{ref: refStr, process: proc, loadedAt: time.Now().UTC()}
	m.mu.Lock()
	if existing, ok := m.instances[refStr]; ok {
		info := infoFor(existing)
		m.mu.Unlock()
		_ = proc.Stop(context.Background())
		return info, nil
	}
	m.instances[refStr] = inst
	info := infoFor(inst)
	m.mu.Unlock()
	return info, nil
}

// Unload stops a resident model.
func (m *Manager) Unload(ctx context.Context, refStr string) error {
	m.mu.Lock()
	inst, ok := m.instances[refStr]
	if ok {
		delete(m.instances, refStr)
	}
	m.mu.Unlock()
	if !ok {
		return nil
	}
	return inst.process.Stop(ctx)
}

// InstanceInfo is the public view of a resident model.
type InstanceInfo struct {
	Ref      string    `json:"ref"`
	State    string    `json:"state"`
	Endpoint string    `json:"endpoint"`
	PID      int       `json:"pid"`
	LoadedAt time.Time `json:"loaded_at"`
}

func infoFor(inst *instance) InstanceInfo {
	return InstanceInfo{
		Ref: inst.ref, State: "ready", Endpoint: inst.process.Endpoint(),
		PID: inst.process.PID(), LoadedAt: inst.loadedAt,
	}
}

// Slots returns the current resident/pending count and configured slot limit.
func (m *Manager) Slots() (int, int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.instances) + m.pending, m.opts.MaxLoaded
}

// Busy reports whether a reference is loaded or currently being loaded.
func (m *Manager) Busy(ref string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.instances[ref]; ok {
		return true
	}
	_, ok := m.loading[ref]
	return ok
}

// List returns resident models.
func (m *Manager) List() []InstanceInfo {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]InstanceInfo, 0, len(m.instances))
	for _, inst := range m.instances {
		out = append(out, infoFor(inst))
	}
	return out
}

// Endpoint returns the loopback endpoint of a loaded model.
func (m *Manager) Endpoint(refStr string) (string, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	inst, ok := m.instances[refStr]
	if !ok || inst.process == nil {
		return "", false
	}
	return inst.process.Endpoint(), true
}

// Close stops all resident models.
func (m *Manager) Close(ctx context.Context) {
	m.mu.Lock()
	instances := m.instances
	m.instances = map[string]*instance{}
	m.mu.Unlock()
	for _, inst := range instances {
		_ = inst.process.Stop(ctx)
	}
}

func (m *Manager) checkCapacityLocked(ctx context.Context, b BundleInfo) error {
	loaded := len(m.instances) + m.pending
	maxLoaded := m.opts.MaxLoaded
	if maxLoaded > 0 && loaded >= maxLoaded {
		return fmt.Errorf("%w: model slot limit reached (%d)", ErrResourceExhausted, maxLoaded)
	}
	if b.MinVRAMMiB <= 0 {
		return nil
	}
	probe := m.opts.GPU
	if probe == nil {
		probe = gpu.Probe
	}
	devices, err := probe(ctx)
	if err != nil {
		return fmt.Errorf("%w: cannot inspect GPU memory: %v", ErrResourceExhausted, err)
	}
	var free int64
	for _, d := range devices {
		if d.MemoryFree > free {
			free = d.MemoryFree
		}
	}
	need := (b.MinVRAMMiB + m.opts.MinFreeVRAMMiB) * 1024 * 1024
	if free < need {
		return fmt.Errorf("%w: need %d MiB free VRAM, have %d MiB", ErrResourceExhausted, b.MinVRAMMiB+m.opts.MinFreeVRAMMiB, free/(1024*1024))
	}
	return nil
}

// BundleInfo is the admission metadata read from a bundle manifest.
type BundleInfo struct {
	Name         string
	RunOnly      bool
	MinVRAMMiB   int64
	ServeOptions []serveopts.Spec
}

func inspectBundle(refStr string) (BundleInfo, error) {
	body, variant, err := ref.SplitVariant(refStr)
	if err != nil {
		return BundleInfo{}, err
	}
	root := body
	if ref.IsFlashHub(refStr) {
		var err error
		root, _, variant, err = host.EnsureBundle(refStr, true, false)
		if err != nil {
			return BundleInfo{}, err
		}
	}
	m, err := manifest.Load(root)
	if err != nil {
		return BundleInfo{}, err
	}
	if _, err := manifest.ResolveVariant(m, variant); err != nil {
		return BundleInfo{}, err
	}
	m, err = host.ApplyEnv(m)
	if err != nil {
		return BundleInfo{}, err
	}
	return BundleInfo{
		Name:         m.Name,
		RunOnly:      m.EntryFor("serve", variant) == nil,
		MinVRAMMiB:   minVRAMMiB(m),
		ServeOptions: serveopts.FromManifest(m, variant),
	}, nil
}

func minVRAMMiB(m *manifest.Manifest) int64 {
	block, _ := m.Raw["resources"].(map[string]any)
	for _, key := range []string{"min_vram_mib", "vram_mib", "min_memory_mib"} {
		if v, ok := numberFromAny(block[key]); ok {
			return v
		}
	}
	return 0
}

func numberFromAny(v any) (int64, bool) {
	switch n := v.(type) {
	case float64:
		return int64(n), true
	case int64:
		return n, true
	case int:
		return int64(n), true
	case string:
		i, err := strconv.ParseInt(strings.TrimSpace(n), 10, 64)
		return i, err == nil
	default:
		return 0, false
	}
}

// endpointFromLog extracts the endpoint printed by `flashcli serve` for native
// backends: "native-exec serve: http://127.0.0.1:1234 (no Python)".
func endpointFromLog(line string) string {
	const marker = "native-exec serve:"
	idx := strings.Index(line, marker)
	if idx < 0 {
		return ""
	}
	rest := strings.TrimSpace(line[idx+len(marker):])
	if i := strings.IndexAny(rest, " \t\r\n"); i >= 0 {
		rest = rest[:i]
	}
	if !strings.HasPrefix(rest, "http://") && !strings.HasPrefix(rest, "https://") {
		return ""
	}
	return strings.TrimRight(rest, "/")
}

// portAvailable reports whether a TCP port can be bound on all interfaces.
func portAvailable(port int) bool {
	ln, err := net.Listen("tcp", "0.0.0.0:"+strconv.Itoa(port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

// freePort asks the OS for any free TCP port. Explicit user ports are checked
// with portAvailable before launch.
func freePort() (int, error) {
	ln, err := net.Listen("tcp", "0.0.0.0:0")
	if err != nil {
		return 0, err
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port, nil
}

// FlashcliLauncher starts `flashcli serve` as a separate process.
type FlashcliLauncher struct {
	Bin        string
	Host       string
	PublicHost string
	LogDir     string
	ExtraEnv   []string
}

func resolveFlashcliBin(bin string) (string, error) {
	bin = strings.TrimSpace(bin)
	if bin == "" {
		bin = strings.TrimSpace(os.Getenv("FLASHCLI_BIN"))
	}
	if bin == "" {
		var err error
		bin, err = exec.LookPath("flashcli")
		if err != nil {
			return "", fmt.Errorf("flashcli binary not found (set FLASHCLI_BIN): %w", err)
		}
	}
	return bin, nil
}

func (l FlashcliLauncher) Start(ctx context.Context, refStr string, port int) (ServeProcess, error) {
	return l.StartWithOptions(ctx, refStr, LoadOptions{Port: port})
}

func (l FlashcliLauncher) StartWithOptions(ctx context.Context, refStr string, opts LoadOptions) (ServeProcess, error) {
	bin, err := resolveFlashcliBin(l.Bin)
	if err != nil {
		return nil, err
	}
	hostAddr := strings.TrimSpace(opts.Host)
	if hostAddr == "" {
		hostAddr = l.Host
	}
	if hostAddr == "" {
		hostAddr = "127.0.0.1"
	}
	publicHost := l.PublicHost
	if publicHost == "" {
		if hostAddr == "0.0.0.0" || hostAddr == "::" || hostAddr == "[::]" {
			publicHost = "127.0.0.1"
		} else {
			publicHost = hostAddr
		}
	}
	args := []string{"serve", refStr, "--host", hostAddr, "--port", strconv.Itoa(opts.Port)}
	args = append(args, opts.Flags...)
	cmd := exec.Command(bin, args...)
	cmd.Env = append(os.Environ(), l.ExtraEnv...)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	logPath := ""
	if l.LogDir != "" {
		if err := os.MkdirAll(l.LogDir, 0o755); err != nil {
			return nil, err
		}
		name := strings.NewReplacer("/", "_", "\\", "_", ":", "_").Replace(refStr) + ".log"
		logPath = filepath.Join(l.LogDir, name)
		f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			return nil, err
		}
		cmd.Stdout = f
		cmd.Stderr = f
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	p := &flashcliProcess{
		ref: refStr, cmd: cmd, port: opts.Port, logPath: logPath,
		endpoint: "http://" + publicHost + ":" + strconv.Itoa(opts.Port),
		client:   &http.Client{Timeout: 5 * time.Second},
		done:     make(chan struct{}),
	}
	go func() {
		p.waitErr = cmd.Wait()
		close(p.done)
	}()
	return p, nil
}

type flashcliProcess struct {
	ref     string
	cmd     *exec.Cmd
	port    int
	client  *http.Client
	logPath string
	done    chan struct{}
	waitErr error

	endpointMu sync.Mutex
	endpoint   string
}

func (p *flashcliProcess) Ref() string { return p.ref }

func (p *flashcliProcess) Endpoint() string {
	p.endpointMu.Lock()
	defer p.endpointMu.Unlock()
	return p.endpoint
}

func (p *flashcliProcess) setEndpoint(endpoint string) {
	p.endpointMu.Lock()
	p.endpoint = endpoint
	p.endpointMu.Unlock()
}

// adoptReportedEndpoint switches to the endpoint a native serve child reported
// ("native-exec serve: http://host:port"). Native http backends choose their
// own port, so the allocated port cannot be assumed.
func (p *flashcliProcess) adoptReportedEndpoint() {
	if u := endpointFromLog(p.LastLog()); u != "" && u != p.Endpoint() {
		p.setEndpoint(u)
	}
}
func (p *flashcliProcess) PID() int {
	if p.cmd.Process == nil {
		return 0
	}
	return p.cmd.Process.Pid
}

// Running reports whether the child has not exited yet.
func (p *flashcliProcess) Running() bool {
	if p.done == nil {
		return false
	}
	select {
	case <-p.done:
		return false
	default:
		return true
	}
}

// LastLog returns the last non-empty line written by the child.
func (p *flashcliProcess) LastLog() string {
	if p.logPath == "" {
		return ""
	}
	f, err := os.Open(p.logPath)
	if err != nil {
		return ""
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return ""
	}
	const tail = 4096
	off := info.Size() - tail
	if off < 0 {
		off = 0
	}
	if _, err := f.Seek(off, 0); err != nil {
		return ""
	}
	blob := make([]byte, info.Size()-off)
	if _, err := f.Read(blob); err != nil && err.Error() != "EOF" {
		return ""
	}
	lines := strings.Split(strings.TrimSpace(string(blob)), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if line := strings.TrimSpace(lines[i]); line != "" {
			return line
		}
	}
	return ""
}

func (p *flashcliProcess) Healthy(ctx context.Context) error {
	// Native http backends report their own endpoint; adopt it before probing.
	p.adoptReportedEndpoint()
	// Python serve exposes /health; native serve (abi/exec) exposes /healthz
	// (docs/bundle_execution_abi.md). Accept either so one supervisor works
	// for both kinds.
	var lastErr error
	for _, path := range []string{"/health", "/healthz"} {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.Endpoint()+path, nil)
		if err != nil {
			return err
		}
		resp, err := p.client.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		_ = resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			return nil
		}
		lastErr = fmt.Errorf("%s HTTP %d", path, resp.StatusCode)
	}
	return lastErr
}

func (p *flashcliProcess) Stop(ctx context.Context) error {
	if p.cmd == nil || p.cmd.Process == nil {
		return nil
	}
	select {
	case <-p.done:
		return nil
	default:
	}
	_ = p.cmd.Process.Signal(os.Interrupt)
	select {
	case <-p.done:
		return nil
	case <-time.After(15 * time.Second):
		_ = p.cmd.Process.Kill()
		<-p.done
		return nil
	case <-ctx.Done():
		_ = p.cmd.Process.Kill()
		<-p.done
		return nil
	}
}
