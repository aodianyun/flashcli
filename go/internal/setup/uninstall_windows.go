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

	if opts.PurgeDistro {
		// No need to start the distro: unregister removes the whole virtual
		// disk (and with it every model/weight/runtime inside).
		i.printf("remove WSL distro %s and its virtual disk (all data inside is lost)\n", opts.Distro)
		_ = exec.CommandContext(ctx, sysExe("wsl.exe"), "--terminate", opts.Distro).Run()
		cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), "--unregister", opts.Distro)
		cmd.Stdout = diag
		cmd.Stderr = diag
		if err := cmd.Run(); err != nil {
			i.printf("warn: wsl --unregister %s: %v\n", opts.Distro, err)
		}
		removeWindowsUninstallArtifacts(ctx, &i, opts)
		i.printf("removed WSL distro %s; its virtual disk was deleted\n", opts.Distro)
		return nil
	}

	// A cold WSL service can reject the first invocations; wait until the
	// distro answers before removing anything.
	if err := waitWSL(ctx, opts); err != nil {
		return err
	}
	home := strings.TrimSpace(opts.Home)
	if home == "" || strings.ContainsAny(home, ":\\") {
		home = "/root/.flashcli"
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
	if opts.PurgeModels {
		// Never delete an unexpected root path.
		if strings.HasPrefix(home, "/") && home != "/" {
			i.printf("remove model caches %s\n", home)
			if err := wslRoot(ctx, opts, "rm", "-rf", home); err != nil {
				i.printf("warn: remove %s: %v\n", home, err)
			}
		} else {
			i.printf("warn: refusing to purge unsafe path %q\n", home)
		}
		if err := wslRoot(ctx, opts, "rm", "-rf", "/usr/local/share/flashcli"); err != nil {
			i.printf("warn: remove bundle source: %v\n", err)
		}
	}
	if opts.RemoveCLI {
		if err := wslRoot(ctx, opts, "rm", "-f", "/usr/local/bin/flashcli"); err != nil {
			i.printf("warn: remove flashcli: %v\n", err)
		}
	}
	removeWindowsUninstallArtifacts(ctx, &i, opts)
	kept := "kept WSL distro " + opts.Distro
	if opts.PurgeModels {
		kept += ", removed model caches"
	} else {
		kept += ", kept model caches"
	}
	i.printf("removed flashserver service/config/binary; %s\n", kept)
	return nil
}

// removeWindowsUninstallArtifacts clears the per-user logon task, the
// keepalive helper and (optionally) the desktop settings. The WSL-side files
// are handled by the caller.
func removeWindowsUninstallArtifacts(ctx context.Context, i *installer, opts Options) {
	task := "flashserver-wsl"
	i.printf("remove Windows logon task %s\n", task)
	cmd := exec.CommandContext(ctx, sysExe("schtasks.exe"), "/Delete", "/F", "/TN", task)
	cmd.Stdout = diag
	cmd.Stderr = diag
	if err := cmd.Run(); err != nil {
		i.printf("logon task removal returned: %v\n", err)
	}
	_ = os.Remove(filepath.Join(os.Getenv("LOCALAPPDATA"), "FlashServer", "wsl-keepalive.vbs"))
	if opts.PurgeSettings {
		dir := filepath.Join(os.Getenv("LOCALAPPDATA"), "FlashServer")
		if err := os.RemoveAll(dir); err != nil {
			i.printf("warn: remove %s: %v\n", dir, err)
		}
	}
}
