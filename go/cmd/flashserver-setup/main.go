package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/aodianyun/flashcli/go/internal/paths"
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
	flag.StringVar(&opts.Distro, "distro", "Ubuntu", "WSL distribution")
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
	flag.StringVar(&opts.WSLDir, "wsl-dir", "", "with --backend wsl: move the Ubuntu distro to this directory (NTFS drive)")
	flag.StringVar(&opts.DistroRootfs, "distro-rootfs", "", "with --backend wsl: import this Ubuntu rootfs tarball instead of downloading the distro")
	flag.BoolVar(&opts.StopService, "stop-service", false, "stop the service and disable auto-start")
	flag.BoolVar(&opts.StartService, "start-service", false, "enable auto-start and start the service")
	flag.BoolVar(&opts.EnableAutostart, "enable-autostart", false, "enable auto-start without starting the service")
	flag.BoolVar(&opts.DisableAutostart, "disable-autostart", false, "disable auto-start without stopping the service")
	progressPath := flag.String("progress-file", "", "write machine-readable setup progress to this file")
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()
	if *showVersion {
		fmt.Println(version.Version)
		return 0
	}
	if (opts.StopService || opts.StartService || opts.EnableAutostart || opts.DisableAutostart) && ensureElevated() {
		return 0
	}

	ctx := context.Background()
	env := setup.Detect(ctx)
	backend := setup.EffectiveBackend(env, opts.Backend)
	logFile := openSetupLog()
	if logFile != nil {
		defer logFile.Close()
		setup.SetLog(logFile)
	}
	out := io.Writer(os.Stdout)
	if logFile != nil {
		out = io.MultiWriter(os.Stdout, logFile)
	}
	var progressFile *os.File
	if *progressPath != "" {
		f, err := os.Create(*progressPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "warn: progress file: %v\n", err)
		} else {
			progressFile = f
			defer progressFile.Close()
			out = io.MultiWriter(out, progressFile)
		}
	}
	fmt.Fprintf(out, "flashserver-setup %s\n", version.Version)
	fmt.Fprintf(out, "System: %s/%s, WSL: %v, backend: %s\n", env.OS, env.Arch, env.WSL, backend)
	if logFile != nil {
		fmt.Fprintf(out, "Log: %s\n", logFile.Name())
	}
	fmt.Fprintln(out)
	if opts.DryRun {
		steps, err := setup.Plan(env, opts.Backend)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			if progressFile != nil {
				fmt.Fprintf(progressFile, "DONE 2\n")
				_ = progressFile.Sync()
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
		fmt.Fprintf(out, "error: %v\n", err)
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		if errors.Is(err, setup.ErrRebootRequired) {
			fmt.Fprintln(out, "\nWindows must be restarted before WSL2 can be used.")
			fmt.Fprintln(out, "Restart the computer, then run Setup again to finish the installation.")
			code = 3
		} else {
			code = 2
		}
	}
	if progressFile != nil {
		fmt.Fprintf(progressFile, "DONE %d\n", code)
		_ = progressFile.Sync()
	}
	return code
}

// openSetupLog writes the full setup trace (including WSL/schtasks output) so
// the UI installer and support can diagnose failures.
func openSetupLog() *os.File {
	dir := filepath.Join(paths.Home(), "logs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil
	}
	f, err := os.OpenFile(filepath.Join(dir, "setup.log"), os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return nil
	}
	return f
}
