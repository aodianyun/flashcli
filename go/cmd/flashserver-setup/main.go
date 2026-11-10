package main

import (
	"context"
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
	flag.BoolVar(&opts.StopService, "stop-service", false, "stop the service and disable auto-start")
	flag.BoolVar(&opts.StartService, "start-service", false, "enable auto-start and start the service")
	flag.BoolVar(&opts.EnableAutostart, "enable-autostart", false, "enable auto-start without starting the service")
	flag.BoolVar(&opts.DisableAutostart, "disable-autostart", false, "disable auto-start without stopping the service")
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()
	if *showVersion {
		fmt.Println(version.Version)
		return
	}
	if (opts.StopService || opts.StartService || opts.EnableAutostart || opts.DisableAutostart) && ensureElevated() {
		return
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
			os.Exit(2)
		}
		for i, step := range steps {
			fmt.Fprintf(out, "  %d. %-16s %s\n", i+1, step.Name, step.Description)
		}
		fmt.Fprintln(out)
	}
	if err := setup.Run(ctx, env, opts, out); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(2)
	}
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
