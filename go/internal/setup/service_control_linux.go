//go:build linux

package setup

import (
	"context"
	"fmt"
	"io"
	"os"
)

const autostartMarker = "/etc/flashserver/autostart"

func stopService(ctx context.Context, env Env, opts Options, out io.Writer) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("service control requires root; rerun with sudo")
	}
	i := installer{env: env, opts: opts, out: out}
	if err := i.run(ctx, "systemctl", "disable", "--now", opts.ServiceName); err != nil {
		return err
	}
	_ = os.WriteFile(autostartMarker, []byte("disabled\n"), 0o644)
	fmt.Fprintln(out, "FlashServer stopped and auto-start disabled.")
	fmt.Fprintln(out, "Start it again with `sudo flashserver-setup --start-service`.")
	return nil
}

func enableAutostart(ctx context.Context, env Env, opts Options, out io.Writer) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("service control requires root; rerun with sudo")
	}
	i := installer{env: env, opts: opts, out: out}
	if err := i.run(ctx, "systemctl", "enable", opts.ServiceName); err != nil {
		return err
	}
	_ = os.WriteFile(autostartMarker, []byte("enabled\n"), 0o644)
	fmt.Fprintln(out, "Auto-start enabled; FlashServer is not started.")
	return nil
}

func disableAutostart(ctx context.Context, env Env, opts Options, out io.Writer) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("service control requires root; rerun with sudo")
	}
	i := installer{env: env, opts: opts, out: out}
	if err := i.run(ctx, "systemctl", "disable", opts.ServiceName); err != nil {
		return err
	}
	_ = os.WriteFile(autostartMarker, []byte("disabled\n"), 0o644)
	fmt.Fprintln(out, "Auto-start disabled; FlashServer is still running.")
	return nil
}

func startService(ctx context.Context, env Env, opts Options, out io.Writer) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("service control requires root; rerun with sudo")
	}
	i := installer{env: env, opts: opts, out: out}
	if err := i.run(ctx, "systemctl", "enable", "--now", opts.ServiceName); err != nil {
		return err
	}
	_ = os.WriteFile(autostartMarker, []byte("enabled\n"), 0o644)
	fmt.Fprintln(out, "FlashServer started and auto-start enabled.")
	fmt.Fprintln(out, "Console: http://localhost:8790/")
	return nil
}
