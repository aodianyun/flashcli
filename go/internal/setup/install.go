package setup

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// ErrRebootRequired reports that Windows must be restarted before WSL2 can be
// used. The setup command maps it to exit code 3 (the UI installer offers a
// restart and asks the user to run setup again).
var ErrRebootRequired = errors.New("restart required to finish enabling WSL2")

// Options controls installation.
type Options struct {
	Backend          string
	DryRun           bool
	BinDir           string
	Prefix           string
	Home             string
	User             string
	Distro           string
	Addr             string
	Token            string
	ServiceName      string
	ConfigPath       string
	NoService        bool
	ReleaseVersion   string
	ReleaseBase      string
	ReleaseAPI       string
	Uninstall        bool
	PurgeModels      bool
	RemoveCLI        bool
	PurgeSettings    bool
	PurgeDistro      bool
	WSLDir           string
	DistroRootfs     string
	StopService      bool
	StartService     bool
	EnableAutostart  bool
	DisableAutostart bool
	PathEnv          string
}

// Run installs flashserver for the detected platform.
func Run(ctx context.Context, env Env, opts Options, out io.Writer) error {
	opts = normalizeOptions(env, opts)
	if opts.DryRun {
		return nil
	}
	stopHeartbeat := startHeartbeat(out, 15*time.Second)
	defer stopHeartbeat()
	if opts.Uninstall {
		return uninstall(ctx, env, opts, out)
	}
	if opts.EnableAutostart {
		return enableAutostart(ctx, env, opts, out)
	}
	if opts.DisableAutostart {
		return disableAutostart(ctx, env, opts, out)
	}
	if opts.StopService {
		return stopService(ctx, env, opts, out)
	}
	if opts.StartService {
		return startService(ctx, env, opts, out)
	}
	cleanup, err := ensureAssetBinaries(ctx, env, &opts, out)
	if err != nil {
		return err
	}
	defer cleanup()
	backend := EffectiveBackend(env, opts.Backend)
	switch backend {
	case "native":
		return installLinux(ctx, env, opts, out)
	case "wsl":
		return installWSL(ctx, env, opts, out)
	default:
		return fmt.Errorf("unknown backend %q", backend)
	}
}

func normalizeOptions(env Env, opts Options) Options {
	if opts.Backend == "" {
		opts.Backend = "auto"
	}
	if opts.BinDir == "" {
		opts.BinDir = executableDir()
	}
	if opts.Prefix == "" {
		opts.Prefix = "/usr/local"
	}
	if opts.User == "" {
		if u := strings.TrimSpace(os.Getenv("SUDO_USER")); u != "" {
			opts.User = u
		} else {
			opts.User = currentUser()
		}
	}
	if opts.Home == "" {
		opts.Home = homeForUser(opts.User)
	}
	if opts.Distro == "" {
		opts.Distro = "Ubuntu"
	}
	if opts.Addr == "" {
		opts.Addr = "127.0.0.1:8790"
	}
	// Authentication is off by default: this is a single-user local daemon.
	// Pass --token to require X-Flashcli-Token/Bearer on every API call.
	if opts.ServiceName == "" {
		opts.ServiceName = "flashserver"
	}
	if opts.ConfigPath == "" {
		opts.ConfigPath = "/etc/flashserver/config.json"
	}
	return opts
}

type installer struct {
	env  Env
	opts Options
	out  io.Writer
}

// activeStep tracks the step currently running so the heartbeat can explain a
// long quiet period (for example while `wsl --install` waits on the Store).
var activeStep struct {
	mu    sync.Mutex
	name  string
	since time.Time
}

// startHeartbeat periodically writes a line to out while a step is active.
// The returned function stops the goroutine. Callers must serialize writes to
// out (the setup command uses a mutex-protected writer).
func startHeartbeat(out io.Writer, interval time.Duration) func() {
	done := make(chan struct{})
	var once sync.Once
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				activeStep.mu.Lock()
				name, since := activeStep.name, activeStep.since
				activeStep.mu.Unlock()
				if name == "" {
					continue
				}
				fmt.Fprintf(out, "  %s: still working (%ds)\n", name, int(time.Since(since).Seconds()))
			}
		}
	}()
	return func() { once.Do(func() { close(done) }) }
}

// diag receives child-process output (wsl.exe, schtasks.exe). It defaults to
// discard so the user-facing output stays clean; main redirects it to a log.
var diag io.Writer = io.Discard

// SetLog redirects child-process diagnostics to w.
func SetLog(w io.Writer) {
	if w != nil {
		diag = w
	}
}

func (i installer) printf(format string, args ...any) {
	fmt.Fprintf(i.out, format, args...)
}

func (i installer) run(ctx context.Context, name string, args ...string) error {
	if i.opts.DryRun {
		i.printf("$ %s %s\n", name, strings.Join(args, " "))
		return nil
	}
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Stdout = i.out
	cmd.Stderr = i.out
	return cmd.Run()
}

// runDiag is like run but sends child output to the diagnostic log instead of
// the progress stream. Windows tools (notably wsl.exe) emit UTF-16LE, which
// would otherwise show up as spaced-out garbage in the installer's log view.
func (i installer) runDiag(ctx context.Context, name string, args ...string) error {
	if i.opts.DryRun {
		i.printf("$ %s %s\n", name, strings.Join(args, " "))
		return nil
	}
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Stdout = diag
	cmd.Stderr = diag
	return cmd.Run()
}

func (i installer) writeFile(path string, data []byte, mode os.FileMode, desc string) error {
	i.printf("write %s (%s)\n", path, desc)
	if i.opts.DryRun {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, mode)
}

func (i installer) copyBinary(name, dest string) error {
	src := resolveBinary(i.opts.BinDir, name, i.env.OS, i.env.Arch)
	i.printf("install %s -> %s\n", src, dest)
	if i.opts.DryRun || filepath.Clean(src) == filepath.Clean(dest) {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("%s: %w", src, err)
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	// Write a sibling temp file and rename it into place: replacing a running
	// executable in place fails with ETXTBSY, an atomic rename does not.
	tmp := dest + ".tmp"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		_ = os.Remove(tmp)
		return err
	}
	if err := out.Close(); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, dest); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func resolveBinary(dir, name, goos, goarch string) string {
	candidates := []string{
		filepath.Join(dir, name),
		filepath.Join(dir, name+"-"+goos+"-"+goarch),
	}
	for _, p := range candidates {
		if info, err := os.Stat(p); err == nil && !info.IsDir() {
			return p
		}
	}
	return candidates[0]
}

// sysExe resolves a Windows system utility by absolute path. Go's exec refuses
// PATH hits that resolve relative to the current directory, and elevated
// processes are often started in C:\Windows\System32. On other platforms the
// name is returned unchanged.
func sysExe(name string) string {
	if root := os.Getenv("SystemRoot"); root != "" {
		p := filepath.Join(root, "System32", name)
		if info, err := os.Stat(p); err == nil && !info.IsDir() {
			return p
		}
	}
	return name
}

func currentUser() string {
	if u := strings.TrimSpace(os.Getenv("USER")); u != "" {
		return u
	}
	if u := strings.TrimSpace(os.Getenv("USERNAME")); u != "" {
		return u
	}
	return "root"
}

func userHome() string {
	h, err := os.UserHomeDir()
	if err != nil || h == "" {
		return "."
	}
	return h
}

func homeForUser(name string) string {
	if name == "" {
		return filepath.Join(userHome(), ".flashcli")
	}
	if u, err := user.Lookup(name); err == nil && u.HomeDir != "" {
		return filepath.Join(u.HomeDir, ".flashcli")
	}
	return filepath.Join(userHome(), ".flashcli")
}

func executableDirOf(exe string) string {
	return filepath.Dir(exe)
}
