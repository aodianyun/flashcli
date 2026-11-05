//go:build windows

package setup

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"strings"
	"time"
)

func installWSL(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if err := wslAvailable(ctx); err != nil {
		return err
	}
	if err := ensureDistro(ctx, opts, &i); err != nil {
		return err
	}
	if err := ensureSystemd(ctx, opts, &i); err != nil {
		return err
	}
	if strings.ContainsAny(opts.Home, ":\\") {
		opts.Home = "/root/.flashcli"
	}
	opts.User = "root"
	linuxArch := env.Arch
	binDir := path.Join(opts.Prefix, "bin")
	if err := copyToWSL(ctx, opts, resolveBinary(opts.BinDir, "flashcli", "linux", linuxArch), path.Join(binDir, "flashcli")); err != nil {
		return err
	}
	if err := copyToWSL(ctx, opts, resolveBinary(opts.BinDir, "flashserver", "linux", linuxArch), path.Join(binDir, "flashserver")); err != nil {
		return err
	}
	cfg, err := json.MarshalIndent(map[string]any{
		"addr":              exposedAddr(opts.Addr),
		"token":             opts.Token,
		"flashcli_bin":      path.Join(binDir, "flashcli"),
		"public_host":       "localhost",
		"serve_host":        "0.0.0.0",
		"log_dir":           path.Join(opts.Home, "logs", "serve"),
		"max_loaded":        0,
		"min_free_vram_mib": 2048,
	}, "", "  ")
	if err != nil {
		return err
	}
	if err := writeToWSL(ctx, opts, opts.ConfigPath, append(cfg, '\n'), 0o600); err != nil {
		return err
	}
	unit := systemdUnit(opts, binDir)
	if err := writeToWSL(ctx, opts, "/etc/systemd/system/"+opts.ServiceName+".service", []byte(unit), 0o644); err != nil {
		return err
	}
	if err := wslRoot(ctx, opts, "systemctl", "daemon-reload"); err != nil {
		return err
	}
	if err := wslRoot(ctx, opts, "systemctl", "enable", "--now", opts.ServiceName); err != nil {
		return err
	}
	if err := createStartupTask(ctx, opts, &i); err != nil {
		return err
	}
	if opts.DryRun {
		return nil
	}
	return waitHealth(ctx, opts.Addr, opts.Token)
}

func wslAvailable(ctx context.Context) error {
	c, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	if err := exec.CommandContext(c, "wsl.exe", "--status").Run(); err != nil {
		return fmt.Errorf("WSL2 is not available; run `wsl --install` as administrator: %w", err)
	}
	return nil
}

func ensureDistro(ctx context.Context, opts Options, i *installer) error {
	if err := wslRoot(ctx, opts, "true"); err == nil {
		return nil
	}
	if opts.DryRun {
		i.printf("$ wsl.exe --install -d %s\n", opts.Distro)
		return nil
	}
	if err := i.run(ctx, "wsl.exe", "--install", "-d", opts.Distro); err != nil {
		return fmt.Errorf("install WSL distro %s: %w", opts.Distro, err)
	}
	for deadline := time.Now().Add(2 * time.Minute); time.Now().Before(deadline); {
		if err := wslRoot(ctx, opts, "true"); err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
	return fmt.Errorf("WSL distro %s did not become available; complete the WSL install (a reboot may be required) and rerun", opts.Distro)
}

func ensureSystemd(ctx context.Context, opts Options, i *installer) error {
	script := "grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null || printf '[boot]\\nsystemd=true\\n' >> /etc/wsl.conf"
	if opts.DryRun {
		i.printf("$ wsl.exe -d %s -u root -- sh -c %q\n", opts.Distro, script)
		return nil
	}
	if err := wslRoot(ctx, opts, "sh", "-c", script); err != nil {
		return err
	}
	// A changed wsl.conf needs a distro restart before systemd is available.
	if err := wslRoot(ctx, opts, "systemctl", "is-system-running"); err != nil {
		_ = exec.CommandContext(ctx, "wsl.exe", "--shutdown").Run()
		time.Sleep(time.Second)
	}
	return nil
}

func copyToWSL(ctx context.Context, opts Options, src, dest string) error {
	if opts.DryRun {
		fmt.Fprintf(os.Stdout, "$ install %s -> %s (WSL %s)\n", src, dest, opts.Distro)
		return nil
	}
	f, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("%s: %w", src, err)
	}
	defer f.Close()
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(dest) + " && chmod 755 " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, "wsl.exe", "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
	cmd.Stdin = f
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func writeToWSL(ctx context.Context, opts Options, dest string, data []byte, mode os.FileMode) error {
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(filepath.ToSlash(dest)) + " && chmod " + fmt.Sprintf("%o", mode) + " " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, "wsl.exe", "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
	cmd.Stdin = strings.NewReader(string(data))
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if opts.DryRun {
		fmt.Fprintf(os.Stdout, "$ write %s (WSL %s)\n", dest, opts.Distro)
		return nil
	}
	return cmd.Run()
}

func wslRoot(ctx context.Context, opts Options, name string, args ...string) error {
	base := []string{"-d", opts.Distro, "-u", "root", "--", name}
	cmd := exec.CommandContext(ctx, "wsl.exe", append(base, args...)...)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func createStartupTask(ctx context.Context, opts Options, i *installer) error {
	task := "flashserver-wsl"
	command := fmt.Sprintf("wsl.exe -d %s -u root systemctl start %s", opts.Distro, opts.ServiceName)
	i.printf("create Windows startup task %s: %s\n", task, command)
	if opts.DryRun {
		return nil
	}
	cmd := exec.CommandContext(ctx, "schtasks.exe", "/Create", "/F", "/SC", "ONSTART", "/TN", task, "/TR", command, "/RU", "SYSTEM", "/RL", "HIGHEST")
	cmd.Stdout = i.out
	cmd.Stderr = i.out
	return cmd.Run()
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}

func exposedAddr(addr string) string {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return "0.0.0.0:8790"
	}
	if host == "127.0.0.1" || host == "localhost" || host == "" {
		host = "0.0.0.0"
	}
	return net.JoinHostPort(host, port)
}
