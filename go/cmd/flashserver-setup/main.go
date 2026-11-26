package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/setup"
	"github.com/aodianyun/flashcli/go/internal/version"
)

func main() {
	os.Exit(run())
}

func run() int {
	var opts setup.Options
	flag.StringVar(&opts.Backend, "backend", "auto", "backend: auto, native, or wsl")
	flag.BoolVar(&opts.DryRun, "dry-run", false, "print the installation plan and commands without changing the host")
	flag.StringVar(&opts.BinDir, "bin-dir", "", "directory containing flashcli and flashserver binaries")
	flag.StringVar(&opts.Prefix, "prefix", "/usr/local", "installation prefix")
	flag.StringVar(&opts.Home, "home", "", "FLASHCLI_HOME for the service")
	flag.StringVar(&opts.User, "user", "", "service user")
	flag.StringVar(&opts.Distro, "distro", "flashserver_ubuntu", "WSL distribution")
	flag.StringVar(&opts.Addr, "addr", "127.0.0.1:8790", "flashserver listen address")
	flag.StringVar(&opts.Token, "token", "", "local API token (generated when omitted)")
	flag.StringVar(&opts.ServiceName, "service-name", "flashserver", "service name")
	flag.StringVar(&opts.ConfigPath, "config", "/etc/flashserver/config.json", "flashserver config path")
	flag.BoolVar(&opts.NoService, "no-service", false, "install binaries/config only; do not install or start a service")
	flag.StringVar(&opts.ReleaseVersion, "release-version", "", "release version to download (default: this setup build; dev uses latest)")
	flag.StringVar(&opts.ReleaseBase, "release-base", "", "release asset base URL")
	flag.StringVar(&opts.ReleaseAPI, "release-api", "", "release API URL")
	flag.BoolVar(&opts.Uninstall, "uninstall", false, "remove the flashserver service/config/binary (keeps model caches)")
	flag.BoolVar(&opts.PurgeModels, "purge-models", false, "with --uninstall: also delete FLASHCLI_HOME (bundles, weights, runtimes, caches)")
	flag.BoolVar(&opts.RemoveCLI, "remove-cli", false, "with --uninstall: also delete the flashcli binary")
	flag.BoolVar(&opts.PurgeSettings, "purge-settings", false, "with --uninstall: also delete the desktop client settings")
	flag.BoolVar(&opts.PurgeDistro, "purge-distro", false, "with --uninstall (WSL): unregister the Ubuntu distro and delete its virtual disk (all data inside is lost)")
	flag.StringVar(&opts.WSLDir, "wsl-dir", "", "with --backend wsl: place or move the distro at this directory")
	flag.BoolVar(&opts.AllowGlobalWSLShutdown, "allow-global-wsl-shutdown", false, "authorize stopping all WSL distributions if a target-only move fails")
	flag.StringVar(&opts.DistroRootfs, "distro-rootfs", "", "with --backend wsl: import this Ubuntu rootfs tarball instead of downloading the distro")
	flag.BoolVar(&opts.StopService, "stop-service", false, "stop the service and disable auto-start")
	flag.BoolVar(&opts.StartService, "start-service", false, "enable auto-start and start the service")
	flag.BoolVar(&opts.EnableAutostart, "enable-autostart", false, "enable auto-start without starting the service")
	flag.BoolVar(&opts.DisableAutostart, "disable-autostart", false, "disable auto-start without stopping the service")
	progressPath := flag.String("progress-file", "", "write machine-readable setup progress to this file")
	cancelPath := flag.String("cancel-file", "", "watch this file for a setup cancellation request")
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()
	opts.CancelFile = *cancelPath
	if *showVersion {
		fmt.Println(version.Version)
		return 0
	}
	if (opts.StopService || opts.StartService || opts.EnableAutostart || opts.DisableAutostart) && ensureElevated() {
		return 0
	}

	progressWriter := &appendFile{path: *progressPath}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	if *cancelPath != "" {
		stopWatching := watchCancelFile(*cancelPath, cancel)
		defer func() { stopWatching(); _ = os.Remove(*cancelPath) }()
	}
	logSession, logErr := openSetupLog()
	if errors.Is(logErr, ErrSetupAlreadyRunning) {
		fmt.Fprintln(os.Stderr, logErr)
		writeProgressResult(*progressPath, 2, logErr.Error())
		return 2
	}
	if logErr != nil && logSession == nil {
		fmt.Fprintf(os.Stderr, "cannot safely start setup: %v\n", logErr)
		writeProgressResult(*progressPath, 2, logErr.Error())
		return 2
	}
	if logSession != nil {
		defer logSession.Close()
		setup.SetLog(logSession)
		logSession.warningSink = os.Stderr
		if *progressPath != "" {
			logSession.warningSink = io.MultiWriter(os.Stderr, progressWriter)
		}
	}
	var out io.Writer = os.Stdout
	if logSession != nil {
		out = bestEffortOutput{out, logSession}
	}
	if *progressPath != "" {
		// Inno reads this file during setup. The UI supplies a unique path so a
		// second installer cannot overwrite the active run's progress.
		_ = os.Remove(*progressPath)
		out = bestEffortOutput{out, progressWriter}
	}
	// The startup probe must be covered by both the unique run log and the
	// fixed setup.log stream that the existing Inno UI tails.
	var logWarning error
	if logErr != nil {
		logWarning = logErr
	}
	out = &syncWriter{w: out}
	env := setup.Detect(ctx)
	backend := setup.EffectiveBackend(env, opts.Backend)
	fmt.Fprintf(out, "flashserver-setup %s\n", version.Version)
	fmt.Fprintf(out, "System: %s/%s, WSL: %v, backend: %s\n", env.OS, env.Arch, env.WSL, backend)
	if logSession != nil && logSession.path() != "" {
		fmt.Fprintf(out, "Log: %s\n", logSession.path())
	}
	if logWarning != nil {
		fmt.Fprintf(out, "warning: setup log is unavailable or incomplete: %v; continuing without complete file logging\n", logWarning)
	}
	fmt.Fprintln(out)
	if opts.DryRun {
		steps, err := setup.Plan(env, opts.Backend)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %s\n", redactSetupLog([]byte(err.Error())))
			if *progressPath != "" {
				fmt.Fprintf(out, "DONE 2\n")
			}
			return 2
		}
		for i, step := range steps {
			fmt.Fprintf(out, "  %d. %-16s %s\n", i+1, step.Name, step.Description)
		}
		fmt.Fprintln(out)
	}
	code := 0
	if err := setup.Run(ctx, env, opts, out); err != nil {
		fmt.Fprintf(out, "error: %s\n", redactSetupLog([]byte(err.Error())))
		fmt.Fprintf(os.Stderr, "error: %s\n", redactSetupLog([]byte(err.Error())))
		if errors.Is(err, setup.ErrRebootRequired) {
			fmt.Fprintln(out, "\nWindows must be restarted before WSL2 can be used.")
			fmt.Fprintln(out, "Restart the computer, then run Setup again to finish the installation.")
			code = 3
		} else {
			code = 2
		}
	}
	if ctx.Err() != nil && code == 0 {
		fmt.Fprintln(out, "error: setup was cancelled; no further installation steps will run")
		code = 2
	}
	if *progressPath != "" {
		fmt.Fprintf(out, "DONE %d\n", code)
	}
	return code
}

func watchCancelFile(path string, cancel context.CancelFunc) func() {
	done := make(chan struct{})
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()
		for {
			if _, err := os.Stat(path); err == nil {
				cancel()
				return
			}
			select {
			case <-done:
				return
			case <-ticker.C:
			}
		}
	}()
	return func() { close(done); <-stopped }
}

func writeProgressResult(path string, code int, message string) {
	if path == "" {
		return
	}
	_ = os.Remove(path)
	w := &appendFile{path: path}
	if message != "" {
		_, _ = fmt.Fprintf(w, "error: %s\n", message)
	}
	_, _ = fmt.Fprintf(w, "DONE %d\n", code)
}

// appendFile writes each chunk by opening, appending and closing the file so
// another process (the installer UI) can read it at any time.
type appendFile struct {
	path string
	mu   sync.Mutex
}

// syncWriter serializes writes from the setup goroutine and its heartbeat.
type syncWriter struct {
	mu sync.Mutex
	w  io.Writer
}

func (w *syncWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	_, err := w.w.Write(redactSetupLog(p))
	return len(p), err
}

func (w *appendFile) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	written := len(p)
	p = redactSetupLog(p)
	f, err := os.OpenFile(w.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		fmt.Fprintln(os.Stderr, "warning: progress file unavailable; diagnostics may not be persisted")
		return written, nil
	}
	n, werr := f.Write(p)
	if cerr := f.Close(); werr == nil {
		werr = cerr
	}
	if werr == nil && n != len(p) {
		werr = io.ErrShortWrite
	}
	return written, werr
}

// A broken console or progress pipe must not prevent writes to the log sinks.
type bestEffortOutput []io.Writer

func (writers bestEffortOutput) Write(p []byte) (int, error) {
	for _, writer := range writers {
		n, err := writer.Write(p)
		if err != nil || n != len(p) {
			fmt.Fprintln(os.Stderr, "warning: an output channel failed; diagnostics may be incomplete")
		}
	}
	return len(p), nil
}
