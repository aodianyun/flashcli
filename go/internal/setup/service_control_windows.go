//go:build windows

package setup

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os/exec"
)

const autostartMarker = "/etc/flashserver/autostart"

// stopService stops the WSL service, disables auto-start and removes the
// keepalive session.
func stopService(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if err := waitWSL(ctx, opts); err == nil {
		_ = wslRoot(ctx, opts, "systemctl", "disable", "--now", opts.ServiceName)
		_ = wslRoot(ctx, opts, "pkill", "-f", "sleep infinity")
		_ = writeToWSL(ctx, opts, autostartMarker, []byte("disabled\n"), 0o644)
	} else {
		i.printf("warn: WSL is not reachable: %v\n", err)
	}
	var buf bytes.Buffer
	cmd := exec.CommandContext(ctx, sysExe("schtasks.exe"), "/Change", "/TN", "flashserver-wsl", "/DISABLE")
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if err := cmd.Run(); err != nil {
		i.printf("warn: disable logon task: %v (%s)\n", err, bytes.TrimSpace(buf.Bytes()))
	}
	fmt.Fprintln(out, "FlashServer stopped and auto-start disabled.")
	fmt.Fprintln(out, "Start it again with `flashserver-setup --start-service`.")
	return nil
}

// enableAutostart registers logon auto-start without starting the service.
func enableAutostart(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if err := waitWSL(ctx, opts); err != nil {
		return err
	}
	if err := wslRoot(ctx, opts, "systemctl", "enable", opts.ServiceName); err != nil {
		return fmt.Errorf("enable systemd unit: %w", err)
	}
	if err := createStartupTask(ctx, opts, &i, false); err != nil {
		return err
	}
	_ = writeToWSL(ctx, opts, autostartMarker, []byte("enabled\n"), 0o644)
	fmt.Fprintln(out, "Auto-start enabled; FlashServer is not started.")
	return nil
}

// disableAutostart removes boot/logon auto-start but leaves the running
// service and keepalive session untouched.
func disableAutostart(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	var firstErr error
	if err := waitWSL(ctx, opts); err == nil {
		if err := wslRoot(ctx, opts, "systemctl", "disable", opts.ServiceName); err != nil {
			firstErr = fmt.Errorf("disable systemd unit: %w", err)
		} else {
			_ = writeToWSL(ctx, opts, autostartMarker, []byte("disabled\n"), 0o644)
		}
	} else {
		firstErr = fmt.Errorf("WSL is not reachable: %w", err)
	}
	var buf bytes.Buffer
	cmd := exec.CommandContext(ctx, sysExe("schtasks.exe"), "/Change", "/TN", "flashserver-wsl", "/DISABLE")
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if err := cmd.Run(); err != nil {
		i.printf("warn: disable logon task: %v (%s)\n", err, bytes.TrimSpace(buf.Bytes()))
	}
	if firstErr != nil {
		return firstErr
	}
	fmt.Fprintln(out, "Auto-start disabled; FlashServer is still running.")
	return nil
}

// startService re-enables the logon task and starts the daemon.
func startService(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if err := waitWSL(ctx, opts); err != nil {
		return err
	}
	if err := wslRoot(ctx, opts, "systemctl", "enable", opts.ServiceName); err != nil {
		return err
	}
	if err := createStartupTask(ctx, opts, &i, true); err != nil {
		return err
	}
	_ = writeToWSL(ctx, opts, autostartMarker, []byte("enabled\n"), 0o644)
	fmt.Fprintln(out, "FlashServer started and auto-start enabled.")
	fmt.Fprintln(out, "Console: http://localhost:8790/")
	return nil
}
