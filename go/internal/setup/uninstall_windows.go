//go:build windows

package setup

import (
	"context"
	"io"
	"os/exec"
)

func uninstallWSL(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	_ = wslRoot(ctx, opts, "systemctl", "disable", "--now", opts.ServiceName)
	_ = wslRoot(ctx, opts, "rm", "-f", "/etc/systemd/system/"+opts.ServiceName+".service")
	_ = wslRoot(ctx, opts, "systemctl", "daemon-reload")
	_ = wslRoot(ctx, opts, "rm", "-f", opts.ConfigPath)
	_ = wslRoot(ctx, opts, "rm", "-f", "/usr/local/bin/flashserver")
	_ = wslRoot(ctx, opts, "systemctl", "reset-failed", opts.ServiceName)
	task := "flashserver-wsl"
	i.printf("remove Windows startup task %s\n", task)
	cmd := exec.CommandContext(ctx, "schtasks.exe", "/Delete", "/F", "/TN", task)
	cmd.Stdout = i.out
	cmd.Stderr = i.out
	if err := cmd.Run(); err != nil {
		i.printf("startup task removal returned: %v\n", err)
	}
	i.printf("removed flashserver service/config/binary; kept WSL distro %s and model caches\n", opts.Distro)
	return nil
}
