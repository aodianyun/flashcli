package main

import (
	"context"
	"flag"
	"fmt"
	"os"

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
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()
	if *showVersion {
		fmt.Println(version.Version)
		return
	}

	ctx := context.Background()
	env := setup.Detect(ctx)
	backend := setup.EffectiveBackend(env, opts.Backend)
	fmt.Printf("flashserver-setup %s\nOS: %s/%s  WSL: %v  backend: %s\n", version.Version, env.OS, env.Arch, env.WSL, backend)
	if opts.DryRun {
		steps, err := setup.Plan(env, opts.Backend)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			os.Exit(2)
		}
		for i, step := range steps {
			fmt.Printf("%d. %-16s %s\n", i+1, step.Name, step.Description)
		}
		fmt.Println()
	}
	if err := setup.Run(ctx, env, opts, os.Stdout); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(2)
	}
}
