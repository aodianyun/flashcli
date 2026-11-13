//go:build linux

package setup

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/user"
	"path/filepath"
	"strconv"

	"github.com/aodianyun/flashcli/go/internal/mirror"
)

// resolveDistro is a no-op on Linux; WSL only exists on Windows.
func resolveDistro(_ context.Context, _ Env, opts Options) Options { return opts }

func installLinux(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if !opts.DryRun && geteuid() != 0 {
		return fmt.Errorf("native installation requires root; rerun with sudo")
	}
	binDir := filepath.Join(opts.Prefix, "bin")
	if err := i.copyBinary("flashcli", filepath.Join(binDir, "flashcli")); err != nil {
		return err
	}
	if err := i.copyBinary("flashserver", filepath.Join(binDir, "flashserver")); err != nil {
		return err
	}
	cfg, err := json.MarshalIndent(map[string]any{
		"addr":              opts.Addr,
		"token":             opts.Token,
		"flashcli_bin":      filepath.Join(binDir, "flashcli"),
		"public_host":       "127.0.0.1",
		"serve_host":        "127.0.0.1",
		"log_dir":           filepath.Join(opts.Home, "logs", "serve"),
		"max_loaded":        0,
		"min_free_vram_mib": 2048,
	}, "", "  ")
	if err != nil {
		return err
	}
	if err := i.writeFile(opts.ConfigPath, append(cfg, '\n'), 0o600, "flashserver config"); err != nil {
		return err
	}
	if err := i.writeFile(filepath.Join(opts.Home, mirror.EnvFile), mirrorEnvContent(), 0o644, "domestic mirrors"); err != nil {
		return err
	}
	if opts.User != "" && opts.User != "root" {
		if u, uerr := user.Lookup(opts.User); uerr == nil {
			uid, _ := strconv.Atoi(u.Uid)
			gid, _ := strconv.Atoi(u.Gid)
			_ = os.Chown(opts.ConfigPath, uid, gid)
		}
	}
	if opts.NoService {
		i.printf("service install skipped; start manually: FLASHCLI_HOME=%s %s --config %s\n", opts.Home, filepath.Join(binDir, "flashserver"), opts.ConfigPath)
		return nil
	}
	unit := systemdUnit(opts, binDir)
	if err := i.writeFile(filepath.Join("/etc/systemd/system", opts.ServiceName+".service"), []byte(unit), 0o644, "systemd service"); err != nil {
		return err
	}
	if err := i.run(ctx, "systemctl", "daemon-reload"); err != nil {
		return err
	}
	if err := i.run(ctx, "systemctl", "enable", opts.ServiceName); err != nil {
		return err
	}
	if err := i.run(ctx, "systemctl", "restart", opts.ServiceName); err != nil {
		return err
	}
	_ = os.WriteFile("/etc/flashserver/autostart", []byte("enabled\n"), 0o644)
	if opts.DryRun {
		return nil
	}
	return waitHealth(ctx, opts.Addr, opts.Token)
}
