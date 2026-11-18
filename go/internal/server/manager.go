package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/serveopts"
)

// ErrResourceExhausted indicates that loading another model would exceed the
// configured slot limit or available GPU memory.
var ErrResourceExhausted = errors.New("resource exhausted")

// ServeProcess, Launcher, OptionLauncher and LoadOptions are shared with
// `flashcli app` through internal/modelrun.
type ServeProcess = modelrun.ServeProcess
type Launcher = modelrun.Launcher
type OptionLauncher = modelrun.OptionLauncher
type LoadOptions = modelrun.LoadOptions

// ManagerOptions controls model admission.
type ManagerOptions struct {
	// MaxLoaded is the maximum number of resident models. Zero means no slot
	// limit; admission then relies on the bundle's resources.min_vram_mib.
	MaxLoaded int
	// GPU returns the current GPU inventory. Nil falls back to gpu.Probe.
	GPU func(context.Context) ([]gpu.Device, error)
	// Inspect reads a bundle's admission metadata. Nil uses inspectBundle.
	Inspect func(string) (BundleInfo, error)
	// ServeSettings stores per-model host/port/serve options. Nil disables them.
	ServeSettings *serveSettingsStore
	// StatePath persists the model-page loaded set so a daemon restart (for
	// example after a reboot with autostart enabled) restores it. Empty
	// disables persistence.
	StatePath string
}

// Manager owns resident serve processes.
type Manager struct {
	mu        sync.Mutex
	instances map[string]*instance
	loading   map[string]chan struct{}
	launcher  Launcher
	opts      ManagerOptions
	pending   int
	// restoring suppresses persistence while RestoreModels replays the saved
	// set, so a model that fails to load now is not dropped from the file.
	restoring bool
}

type instance struct {
	ref      string
	process  ServeProcess
	loadedAt time.Time
	// owners are the applications (and "model" for the model page) that asked
	// for this instance. The process stops only when the last owner releases it,
	// so two applications using the same bundle do not kill each other's model.
	owners map[string]struct{}
}

// ownerModel marks an instance loaded from the model page, which stays until
// the user unloads it explicitly.
const ownerModel = "model"

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
	return m.loadOwned(ctx, refStr, ownerModel, nil)
}

// LoadWithProgress is Load with coarse progress events (bundle/weights/venv).
func (m *Manager) LoadWithProgress(ctx context.Context, refStr string, progress func(phase, message string)) (*InstanceInfo, error) {
	return m.loadOwned(ctx, refStr, ownerModel, progress)
}

// LoadFor loads ref on behalf of one application. The application is recorded
// as an owner; the returned process must be released instead of force-unloaded.
func (m *Manager) LoadFor(ctx context.Context, refStr, owner string) (*InstanceInfo, error) {
	return m.loadOwned(ctx, refStr, owner, nil)
}

// LoadForWithProgress is LoadFor with coarse progress events.
func (m *Manager) LoadForWithProgress(ctx context.Context, refStr, owner string, progress func(phase, message string)) (*InstanceInfo, error) {
	return m.loadOwned(ctx, refStr, owner, progress)
}

func (m *Manager) loadOwned(ctx context.Context, refStr, owner string, progress func(phase, message string)) (*InstanceInfo, error) {
	for {
		m.mu.Lock()
		if inst, ok := m.instances[refStr]; ok {
			// A child that died outside the Manager (crash, OOM kill) must not
			// be handed out as a live instance: reload instead.
			if inst.process.Running() {
				addOwnerLocked(inst, owner)
				if owner == ownerModel && !m.restoring {
					m.persistModelsLocked()
				}
				info := infoFor(inst)
				m.mu.Unlock()
				return &info, nil
			}
			delete(m.instances, refStr)
			m.mu.Unlock()
			_ = inst.process.Stop(context.Background())
			continue
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
		if err == nil {
			if inst, ok := m.instances[refStr]; ok {
				addOwnerLocked(inst, owner)
				if owner == ownerModel && !m.restoring {
					m.persistModelsLocked()
				}
				info = infoFor(inst)
			}
		}
		m.mu.Unlock()
		if err != nil {
			return nil, err
		}
		return &info, nil
	}
}

func addOwnerLocked(inst *instance, owner string) {
	if owner == "" {
		return
	}
	if inst.owners == nil {
		inst.owners = map[string]struct{}{}
	}
	inst.owners[owner] = struct{}{}
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
		if !modelrun.PortAvailable(port) {
			return InstanceInfo{}, fmt.Errorf("serve port %d is already in use", port)
		}
	} else {
		var err error
		port, err = modelrun.FreePort()
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
	// Shared readiness loop with apps.Service: same 250 ms poll and last-log
	// error, so a model start behaves the same from the 模型 page and an app.
	err = modelrun.WaitHealthy(ctx, proc, 120*time.Second, func(line string) {
		if progress != nil {
			progress("progress", line)
		}
	})
	if err != nil {
		_ = proc.Stop(context.Background())
		return InstanceInfo{}, fmt.Errorf("serve process for %s: %w", refStr, err)
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

// Unload stops a resident model regardless of its owners (model page action).
func (m *Manager) Unload(ctx context.Context, refStr string) error {
	_, err := m.UnloadIfLoaded(ctx, refStr)
	return err
}

// UnloadIfLoaded stops a resident model and reports whether it was resident.
func (m *Manager) UnloadIfLoaded(ctx context.Context, refStr string) (bool, error) {
	m.mu.Lock()
	inst, ok := m.instances[refStr]
	if ok {
		delete(m.instances, refStr)
		m.persistModelsLocked()
	}
	m.mu.Unlock()
	if !ok {
		return false, nil
	}
	return true, inst.process.Stop(ctx)
}

// ReleaseFor removes one application's claim on a resident model and stops the
// process only when no owner remains. It reports whether the Manager owned the
// instance (false means the caller should fall back to a recorded pid).
func (m *Manager) ReleaseFor(ctx context.Context, refStr, owner string) (bool, error) {
	m.mu.Lock()
	inst, ok := m.instances[refStr]
	if !ok {
		m.mu.Unlock()
		return false, nil
	}
	if owner != "" {
		delete(inst.owners, owner)
	}
	if len(inst.owners) > 0 {
		m.mu.Unlock()
		return true, nil
	}
	delete(m.instances, refStr)
	m.persistModelsLocked()
	m.mu.Unlock()
	return true, inst.process.Stop(ctx)
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

// Claim registers an owner on an already resident model without starting one.
// It reports false when the Manager does not own that ref (for example a serve
// process started by the CLI), so the caller keeps its own endpoint and the
// Manager does not spawn a duplicate.
func (m *Manager) Claim(refStr, owner string) bool {
	if owner == "" {
		return false
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	inst, ok := m.instances[refStr]
	if !ok || !inst.process.Running() {
		return false
	}
	addOwnerLocked(inst, owner)
	return true
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

// IsRunning reports whether a loaded instance's process is still alive.
func (m *Manager) IsRunning(refStr string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	inst, ok := m.instances[refStr]
	if !ok {
		return false
	}
	return inst.process.Running()
}

// List returns resident models.
func (m *Manager) List() []InstanceInfo {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]InstanceInfo, 0, len(m.instances))
	for ref, inst := range m.instances {
		// Drop children that exited without an unload, so the model page does
		// not advertise a dead instance (and the next load starts fresh).
		if !inst.process.Running() {
			delete(m.instances, ref)
			continue
		}
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

// modelsStateFile is the persisted model-page intent.
type modelsStateFile struct {
	Models []string `json:"models"`
}

// persistModelsLocked writes the model-page loaded set (models with the "model"
// owner); app-only models are restored from the app registry instead.
func (m *Manager) persistModelsLocked() {
	if m.opts.StatePath == "" || m.restoring {
		return
	}
	refs := make([]string, 0, len(m.instances))
	for refStr, inst := range m.instances {
		if _, ok := inst.owners[ownerModel]; ok {
			refs = append(refs, refStr)
		}
	}
	m.writeModelsStateLocked(refs)
}

func (m *Manager) writeModelsStateLocked(refs []string) {
	if m.opts.StatePath == "" {
		return
	}
	sort.Strings(refs)
	blob, err := json.MarshalIndent(modelsStateFile{Models: refs}, "", "  ")
	if err != nil {
		log.Printf("persist loaded models: %v", err)
		return
	}
	if err := os.MkdirAll(filepath.Dir(m.opts.StatePath), 0o755); err != nil {
		log.Printf("persist loaded models: %v", err)
		return
	}
	tmp := m.opts.StatePath + ".tmp"
	if err := os.WriteFile(tmp, append(blob, '\n'), 0o644); err != nil {
		log.Printf("persist loaded models: %v", err)
		return
	}
	if err := os.Rename(tmp, m.opts.StatePath); err != nil {
		log.Printf("persist loaded models: %v", err)
	}
}

// RestoreModels loads the model-page set saved before the daemon stopped (for
// example after a reboot with autostart enabled). Failures are returned; the
// saved set is kept so a later start can retry.
func (m *Manager) RestoreModels(ctx context.Context) []error {
	if m.opts.StatePath == "" {
		return nil
	}
	blob, err := os.ReadFile(m.opts.StatePath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return []error{err}
	}
	var file modelsStateFile
	if err := json.Unmarshal(blob, &file); err != nil {
		return []error{fmt.Errorf("parse %s: %w", m.opts.StatePath, err)}
	}
	if len(file.Models) == 0 {
		return nil
	}
	m.mu.Lock()
	m.restoring = true
	m.mu.Unlock()
	var errs []error
	for _, refStr := range file.Models {
		if _, err := m.Load(ctx, refStr); err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", refStr, err))
		}
	}
	m.mu.Lock()
	m.restoring = false
	// Keep the original intent; a model that could not load now is retried on
	// the next daemon start instead of silently disappearing.
	m.writeModelsStateLocked(file.Models)
	m.mu.Unlock()
	return errs
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
	// Only the bundle declares its requirement; there is no global margin.
	need := b.MinVRAMMiB * 1024 * 1024
	if free < need {
		return fmt.Errorf("%w: need %d MiB free VRAM, have %d MiB", ErrResourceExhausted, b.MinVRAMMiB, free/(1024*1024))
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
