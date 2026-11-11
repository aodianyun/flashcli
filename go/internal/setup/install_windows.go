//go:build windows

package setup

import (
	"bytes"
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
	linuxArch := env.Arch
	binDir := path.Join(opts.Prefix, "bin")
	total := 8
	if opts.DryRun {
		total = 7
	}
	if err := stepf(out, 1, total, "Checking WSL2", func() error { return ensureWSL(ctx, opts, &i) }); err != nil {
		return err
	}
	if err := stepf(out, 2, total, "Preparing Ubuntu", func() error { return ensureDistro(ctx, opts, &i) }); err != nil {
		return err
	}
	if err := stepf(out, 3, total, "Enabling systemd", func() error { return ensureSystemd(ctx, opts, &i) }); err != nil {
		return err
	}
	if strings.ContainsAny(opts.Home, ":\\") {
		opts.Home = "/root/.flashcli"
	}
	opts.User = "root"
	// systemd's default PATH omits the WSL2 driver mount, which hides nvidia-smi
	// from the service and from bundle subprocesses.
	opts.PathEnv = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib"
	if !opts.DryRun {
		addr, err := selectAddr(opts.Addr)
		if err != nil {
			return err
		}
		if addr != opts.Addr {
			i.printf("API address %s is unavailable; using %s\n", opts.Addr, addr)
		}
		opts.Addr = addr
		if err := writeClientAPI(addr); err != nil {
			return fmt.Errorf("write client API URL: %w", err)
		}
	}
	if err := stepf(out, 4, total, "Installing flashcli/flashserver", func() error {
		if err := copyToWSL(ctx, opts, resolveBinary(opts.BinDir, "flashcli", "linux", linuxArch), path.Join(binDir, "flashcli")); err != nil {
			return err
		}
		return copyToWSL(ctx, opts, resolveBinary(opts.BinDir, "flashserver", "linux", linuxArch), path.Join(binDir, "flashserver"))
	}); err != nil {
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
	if err := stepf(out, 5, total, "Writing configuration", func() error {
		if err := writeToWSL(ctx, opts, opts.ConfigPath, append(cfg, '\n'), 0o600); err != nil {
			return err
		}
		unit := systemdUnit(opts, binDir)
		if err := writeToWSL(ctx, opts, "/etc/systemd/system/"+opts.ServiceName+".service", []byte(unit), 0o644); err != nil {
			return err
		}
		return wslRoot(ctx, opts, "systemctl", "daemon-reload")
	}); err != nil {
		return err
	}
	if err := stepf(out, 6, total, "Starting flashserver", func() error {
		if err := wslRoot(ctx, opts, "systemctl", "enable", opts.ServiceName); err != nil {
			return err
		}
		return wslRoot(ctx, opts, "systemctl", "restart", opts.ServiceName)
	}); err != nil {
		return err
	}
	if err := stepf(out, 7, total, "Configuring auto-start", func() error {
		if err := createStartupTask(ctx, opts, &i, true); err != nil {
			return err
		}
		return writeToWSL(ctx, opts, autostartMarker, []byte("enabled\n"), 0o644)
	}); err != nil {
		return err
	}
	if opts.DryRun {
		return nil
	}
	if err := stepf(out, 8, total, "Checking health", func() error { return waitHealth(ctx, opts.Addr, opts.Token) }); err != nil {
		return err
	}
	fmt.Fprintf(out, "\nFlashServer is running: %s/health\n", clientAPIURL())
	fmt.Fprintf(out, "Token/config: /etc/flashserver/config.json (inside WSL)\n")
	return nil
}

// stepf prints a friendly progress line and reports the outcome.
func stepf(out io.Writer, n, total int, name string, fn func() error) error {
	fmt.Fprintf(out, "[%d/%d] %-28s ", n, total, name)
	if err := fn(); err != nil {
		fmt.Fprintln(out, "FAILED")
		return err
	}
	fmt.Fprintln(out, "ok")
	return nil
}

// ensureWSL makes WSL2 available on a clean Windows install. `wsl --install`
// both enables the optional features and installs the WSL app/kernel; when the
// OS still needs a restart it reports ErrRebootRequired so the UI can offer one
// and ask the user to run the installer again.
func ensureWSL(ctx context.Context, opts Options, i *installer) error {
	if wslStatusOK(ctx) {
		return nil
	}
	i.printf("WSL2 not detected; enabling it (this can take several minutes)...\n")
	if opts.DryRun {
		i.printf("$ wsl.exe --install --no-distribution\n")
		return nil
	}

	enableCtx, cancel := context.WithTimeout(ctx, 20*time.Minute)
	wslErr := i.run(enableCtx, sysExe("wsl.exe"), "--install", "--no-distribution")
	cancel()
	if wslErr != nil {
		// Older Windows 10 builds do not know --no-distribution (or --install).
		i.printf("wsl --install failed (%v); enabling the optional features with DISM\n", wslErr)
		dismCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
		err1 := dismEnable(dismCtx, i, "Microsoft-Windows-Subsystem-Linux")
		err2 := dismEnable(dismCtx, i, "VirtualMachinePlatform")
		cancel()
		if err1 != nil && err2 != nil {
			return fmt.Errorf("enable WSL2 features: %v; %v", err1, err2)
		}
	}

	// A newly enabled WSL app or optional feature normally needs a reboot; poll
	// briefly so a machine that is ready without one still proceeds.
	deadline := time.Now().Add(60 * time.Second)
	for {
		if wslStatusOK(ctx) {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("%w: restart Windows, then run Setup again (or run `wsl --install` from an elevated terminal)", ErrRebootRequired)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
}

func wslStatusOK(ctx context.Context) bool {
	c, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return exec.CommandContext(c, sysExe("wsl.exe"), "--status").Run() == nil
}

// dismEnable treats DISM's 3010 (ERROR_SUCCESS_REBOOT_REQUIRED) as success.
func dismEnable(ctx context.Context, i *installer, feature string) error {
	err := i.run(ctx, sysExe("dism.exe"), "/online", "/enable-feature",
		"/featurename:"+feature, "/all", "/norestart")
	if ee, ok := err.(*exec.ExitError); ok && ee.ExitCode() == 3010 {
		i.printf("%s enabled; a restart is required\n", feature)
		return nil
	}
	return err
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
		if !wslStatusOK(ctx) {
			return fmt.Errorf("%w: WSL2 must be restarted before %s can be used (%v)", ErrRebootRequired, opts.Distro, err)
		}
		return fmt.Errorf("install WSL distro %s: %w", opts.Distro, err)
	}
	for deadline := time.Now().Add(10 * time.Minute); time.Now().Before(deadline); {
		if err := wslRoot(ctx, opts, "true"); err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
	if !wslStatusOK(ctx) {
		return fmt.Errorf("%w: restart Windows, then run Setup again to finish installing %s", ErrRebootRequired, opts.Distro)
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
	// "degraded" means systemd is up (some unit failed), so do not restart for
	// it: terminating here races the next WSL command on cold-start.
	if systemdUsable(ctx, opts) {
		return nil
	}
	i.printf("systemd is not running; restarting %s\n", opts.Distro)
	_ = exec.CommandContext(ctx, sysExe("wsl.exe"), "--terminate", opts.Distro).Run()
	return waitWSL(ctx, opts)
}

// systemdUsable reports whether systemd is already running inside the distro.
// systemctl exits 1 for "degraded" and "starting", which are still usable.
func systemdUsable(ctx context.Context, opts Options) bool {
	c, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(c, sysExe("wsl.exe"), "-d", opts.Distro, "-u", "root", "--", "systemctl", "is-system-running")
	out, err := cmd.Output()
	state := strings.TrimSpace(string(out))
	if state != "" {
		fmt.Fprintf(diag, "systemd state: %s\n", state)
	}
	if err == nil {
		return true
	}
	switch state {
	case "degraded", "starting", "initializing", "maintenance":
		return true
	}
	return false
}

func copyToWSL(ctx context.Context, opts Options, src, dest string) error {
	if opts.DryRun {
		fmt.Fprintf(os.Stdout, "$ install %s -> %s (WSL %s)\n", src, dest, opts.Distro)
		return nil
	}
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if err := copyToWSLOnce(ctx, opts, src, dest); err == nil {
			return nil
		} else {
			lastErr = err
		}
		if attempt < 2 {
			// A cold-starting distro can reject the first invocation.
			_ = wslRoot(ctx, opts, "true")
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(2 * time.Second):
			}
		}
	}
	return fmt.Errorf("copy %s -> %s: %w", src, dest, lastErr)
}

func copyToWSLOnce(ctx context.Context, opts Options, src, dest string) error {
	f, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("%s: %w", src, err)
	}
	defer f.Close()
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(dest+".tmp") + " && chmod 755 " + shellQuote(dest+".tmp") + " && mv -f " + shellQuote(dest+".tmp") + " " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
	cmd.Stdin = f
	cmd.Stdout = diag
	cmd.Stderr = diag
	return cmd.Run()
}

func writeToWSL(ctx context.Context, opts Options, dest string, data []byte, mode os.FileMode) error {
	script := "mkdir -p " + shellQuote(path.Dir(dest)) + " && cat > " + shellQuote(filepath.ToSlash(dest)) + " && chmod " + fmt.Sprintf("%o", mode) + " " + shellQuote(dest)
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), "-d", opts.Distro, "-u", "root", "--", "sh", "-c", script)
	cmd.Stdin = strings.NewReader(string(data))
	cmd.Stdout = diag
	cmd.Stderr = diag
	if opts.DryRun {
		fmt.Fprintf(os.Stdout, "$ write %s (WSL %s)\n", dest, opts.Distro)
		return nil
	}
	return cmd.Run()
}

func wslRoot(ctx context.Context, opts Options, name string, args ...string) error {
	base := []string{"-d", opts.Distro, "-u", "root", "--", name}
	cmd := exec.CommandContext(ctx, sysExe("wsl.exe"), append(base, args...)...)
	cmd.Stdout = diag
	cmd.Stderr = diag
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

func createStartupTask(ctx context.Context, opts Options, i *installer, runNow bool) error {
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
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if err := cmd.Run(); err != nil {
		detail := strings.TrimSpace(buf.String())
		if detail != "" {
			return fmt.Errorf("create logon task: %w (%s)", err, detail)
		}
		return fmt.Errorf("create logon task: %w", err)
	}
	// Kick the keepalive now: the distro would otherwise idle-stop (and take
	// the service with it) before the next logon.
	if runNow {
		if err := exec.CommandContext(ctx, sysExe("schtasks.exe"), "/Run", "/TN", task).Run(); err != nil {
			i.printf("warn: could not start logon task %s: %v\n", task, err)
		}
	}
	return nil
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

// selectAddr picks a Windows loopback port that the WSL localhost relay can
// bind. Hyper-V/WinNAT can put the default port (8790) in an excluded range,
// which fails with WSAEACCES even though the Linux daemon is healthy.
func selectAddr(requested string) (string, error) {
	host, port, err := net.SplitHostPort(requested)
	if err != nil {
		host, port = "127.0.0.1", "8790"
	}
	if host != "" && host != "127.0.0.1" && host != "localhost" {
		return requested, nil
	}
	candidates := []string{port}
	for _, p := range []string{"18790", "28790", "38790", "48790"} {
		if p != port {
			candidates = append(candidates, p)
		}
	}
	for _, p := range candidates {
		ln, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", p))
		if err == nil {
			_ = ln.Close()
			return net.JoinHostPort("127.0.0.1", p), nil
		}
	}
	return "", fmt.Errorf("no free local API port (tried %s)", strings.Join(candidates, ", "))
}

// writeClientAPI records the selected URL for the desktop client and the UI
// installer. The client falls back to 8790 when the file is absent.
func writeClientAPI(addr string) error {
	_, port, err := net.SplitHostPort(addr)
	if err != nil {
		return err
	}
	url := "http://127.0.0.1:" + port
	dir := os.Getenv("LOCALAPPDATA")
	if dir == "" {
		return nil
	}
	p := filepath.Join(dir, "FlashServer", "api-url.txt")
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	return os.WriteFile(p, []byte(url+"\n"), 0o644)
}

// clientAPIURL returns the URL written by writeClientAPI (or the default).
func clientAPIURL() string {
	dir := os.Getenv("LOCALAPPDATA")
	if dir != "" {
		if b, err := os.ReadFile(filepath.Join(dir, "FlashServer", "api-url.txt")); err == nil {
			s := strings.TrimSpace(string(b))
			if strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://") {
				return s
			}
		}
	}
	return "http://localhost:8790"
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
