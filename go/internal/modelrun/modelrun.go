// Package modelrun supervises `flashcli serve` child processes. It is shared by
// the resident scheduler (flashserver) and by `flashcli app`, so both use the
// same port allocation, health checks, logging, and stop behavior.
package modelrun

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
)

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

// OptionLauncher is implemented by launchers that accept per-model options.
type OptionLauncher interface {
	StartWithOptions(context.Context, string, LoadOptions) (ServeProcess, error)
}

// LoadOptions carries the per-model host, port and manifest serve flags.
type LoadOptions struct {
	Host  string
	Port  int
	Flags []string
}

// FlashcliLauncher starts `flashcli serve` as a separate process.
type FlashcliLauncher struct {
	Bin        string
	Host       string
	PublicHost string
	LogDir     string
	ExtraEnv   []string
}

// ResolveBin resolves the flashcli binary from an explicit path,
// FLASHCLI_BIN, or PATH.
func ResolveBin(bin string) (string, error) {
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

// Start starts a serve process on the given port.
func (l FlashcliLauncher) Start(ctx context.Context, refStr string, port int) (ServeProcess, error) {
	return l.StartWithOptions(ctx, refStr, LoadOptions{Port: port})
}

// StartWithOptions starts a serve process with per-model options and logs.
func (l FlashcliLauncher) StartWithOptions(ctx context.Context, refStr string, opts LoadOptions) (ServeProcess, error) {
	bin, err := ResolveBin(l.Bin)
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
	p := &process{
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

type process struct {
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

func (p *process) Ref() string { return p.ref }

// Endpoint returns the model endpoint, including any port the child reported.
func (p *process) Endpoint() string {
	p.endpointMu.Lock()
	defer p.endpointMu.Unlock()
	return p.endpoint
}

func (p *process) setEndpoint(endpoint string) {
	p.endpointMu.Lock()
	p.endpoint = endpoint
	p.endpointMu.Unlock()
}

// adoptReportedEndpoint switches to the endpoint a native serve child reported
// ("native-exec serve: http://host:port"). Native http backends choose their
// own port, so the allocated port cannot be assumed.
func (p *process) adoptReportedEndpoint() {
	if u := endpointFromLog(p.LastLog()); u != "" && u != p.Endpoint() {
		p.setEndpoint(u)
	}
}

// PID returns the child pid (0 before start).
func (p *process) PID() int {
	if p.cmd.Process == nil {
		return 0
	}
	return p.cmd.Process.Pid
}

// Running reports whether the child has not exited yet.
func (p *process) Running() bool {
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
func (p *process) LastLog() string {
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
	if _, err := f.Read(blob); err != nil && !errors.Is(err, os.ErrClosed) && err.Error() != "EOF" {
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

// Healthy probes /health then /healthz (native backends).
func (p *process) Healthy(ctx context.Context) error {
	p.adoptReportedEndpoint()
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

// Stop interrupts the child, then kills it after 15s or when ctx ends.
func (p *process) Stop(ctx context.Context) error {
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

// HealthyEndpoint probes /health then /healthz on an already running model.
func HealthyEndpoint(ctx context.Context, endpoint string) error {
	if strings.TrimSpace(endpoint) == "" {
		return errors.New("empty model endpoint")
	}
	client := &http.Client{Timeout: 5 * time.Second}
	var lastErr error
	for _, path := range []string{"/health", "/healthz"} {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(endpoint, "/")+path, nil)
		if err != nil {
			return err
		}
		resp, err := client.Do(req)
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

// PortAvailable reports whether a TCP port can be bound on all interfaces.
func PortAvailable(port int) bool {
	ln, err := net.Listen("tcp", "0.0.0.0:"+strconv.Itoa(port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

// FreePort asks the OS for any free TCP port.
func FreePort() (int, error) {
	ln, err := net.Listen("tcp", "0.0.0.0:0")
	if err != nil {
		return 0, err
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port, nil
}
