//go:build windows

package setup

import (
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func uninstallWSL(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	// A cold WSL service can reject the first invocations; wait until the
	// distro answers before removing anything.
	if err := waitWSL(ctx, opts); err != nil {
		return err
	}
	steps := [][]string{
		{"systemctl", "disable", "--now", opts.ServiceName},
		{"rm", "-f", "/etc/systemd/system/" + opts.ServiceName + ".service"},
		{"systemctl", "daemon-reload"},
		{"rm", "-f", opts.ConfigPath},
		{"rm", "-f", "/usr/local/bin/flashserver"},
		{"systemctl", "reset-failed", opts.ServiceName},
		{"pkill", "-f", "sleep infinity"},
	}
	for _, step := range steps {
		if err := wslRoot(ctx, opts, step[0], step[1:]...); err != nil {
			i.printf("warn: %s: %v\n", strings.Join(step, " "), err)
		}
	}
	task := "flashserver-wsl"
	i.printf("remove Windows logon task %s\n", task)
	cmd := exec.CommandContext(ctx, sysExe("schtasks.exe"), "/Delete", "/F", "/TN", task)
	cmd.Stdout = i.out
	cmd.Stderr = i.out
	if err := cmd.Run(); err != nil {
		i.printf("logon task removal returned: %v\n", err)
	}
	_ = os.Remove(filepath.Join(os.Getenv("LOCALAPPDATA"), "FlashServer", "wsl-keepalive.vbs"))
	i.printf("removed flashserver service/config/binary; kept WSL distro %s and model caches\n", opts.Distro)
	return nil
}
