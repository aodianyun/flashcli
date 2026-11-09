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
	// systemd's default PATH omits the WSL2 driver mount, which hides nvidia-smi
	// from the service and from bundle subprocesses.
	opts.PathEnv = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib"
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
	if err := wslRoot(ctx, opts, "systemctl", "enable", opts.ServiceName); err != nil {
		return err
	}
	if err := wslRoot(ctx, opts, "systemctl", "restart", opts.ServiceName); err != nil {
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
	if err := exec.CommandContext(c, sysExe("wsl.exe"), "--status").Run(); err != nil {
		return fmt.Errorf("WSL2 is not available; run `wsl --install` as administrator: %w", err)
	}
	return nil
}

func ensureDistro(ctx context.Context, opts Options, i *installer) error {
	// Cold-starting the WSL service can make the first calls fail briefly.
	for attempt := 0; attempt < 5; attempt++ {
		if err := wslRoot(ctx, opts, "true"); err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	if opts.DryRun {
		i.printf("$ wsl.exe --install -d %s\n", opts.Distro)
		return nil
	}
	if err := i.run(ctx, sysExe("wsl.exe"), "--install", "-d", opts.Distro, "--no-launch"); err != nil {
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
		_ = exec.CommandContext(ctx, sysExe("wsl.exe"), "--terminate", opts.Distro).Run()
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
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(dest+".tmp") + " && chmod 755 " + shellQuote(dest+".tmp") + " && mv -f " + shellQuote(dest+".tmp") + " " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
	cmd.Stdin = f
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func writeToWSL(ctx context.Context, opts Options, dest string, data []byte, mode os.FileMode) error {
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(filepath.ToSlash(dest)) + " && chmod " + fmt.Sprintf("%o", mode) + " " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
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
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), append(base, args...)...)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// waitWSL blocks until the distro accepts a trivial command. A cold WSL
// service rejects the first invocations, which used to make uninstall a no-op.
func waitWSL(ctx context.Context, opts Options) error {
	deadline := time.Now().Add(60 * time.Second)
	var lastErr error
	for {
		if err := wslRoot(ctx, opts, "true"); err == nil {
			return nil
		} else {
			lastErr = err
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("WSL distro %s is not responding: %v; run `wsl -d %s` once and retry", opts.Distro, lastErr, opts.Distro)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

func createStartupTask(ctx context.Context, opts Options, i *installer) error {
	task := "flashserver-wsl"
	user := currentUserQualified()
	vbs, err := wslKeepaliveScript(opts)
	if err != nil {
		return err
	}
	command := `wscript.exe //B "` + vbs + `"`
	i.printf("create Windows logon task %s (%s): %s\n", task, user, command)
	if opts.DryRun {
		return nil
	}
	// WSL distros are registered per user, so a SYSTEM/boot task cannot start
	// them (schtasks last result 0xFFFFFFFF). Run at logon in the user's session.
	args := []string{"/Create", "/F", "/SC", "ONLOGON", "/TN", task, "/TR", command}
	if user != "" {
		args = append(args, "/RU", user, "/IT")
	}
	cmd := exec.CommandContext(ctx, sysExe("schtasks.exe"), args...)
	cmd.Stdout = i.out
	cmd.Stderr = i.out
	return cmd.Run()
}

// wslKeepaliveScript writes a hidden logon script. WSL's vmIdleTimeout stops
// the distro (and with it the resident service) after a minute without a
// session, so keep a background `sleep infinity` session alive.
func wslKeepaliveScript(opts Options) (string, error) {
	dir := filepath.Join(os.Getenv("LOCALAPPDATA"), "FlashServer")
	path := filepath.Join(dir, "wsl-keepalive.vbs")
	if opts.DryRun {
		return path, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	distro := strings.ReplaceAll(opts.Distro, `"`, "")
	service := strings.ReplaceAll(opts.ServiceName, `"`, "")
	script := fmt.Sprintf(`Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d %s -u root systemctl start %s", 0, True
sh.Run "wsl.exe -d %s -u root -e sleep infinity", 0, False
`, distro, service, distro)
	if err := os.WriteFile(path, []byte(script), 0o644); err != nil {
		return "", err
	}
	return path, nil
}

func currentUserQualified() string {
	name := strings.TrimSpace(os.Getenv("USERNAME"))
	if name == "" {
		return ""
	}
	if domain := strings.TrimSpace(os.Getenv("USERDOMAIN")); domain != "" {
		return domain + `\` + name
	}
	return name
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
