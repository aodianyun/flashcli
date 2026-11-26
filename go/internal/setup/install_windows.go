//go:build windows

package setup

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/version"
)

// resolveDistro keeps existing Ubuntu installs working while new installs use
// a dedicated flashserver_ubuntu distro. WSL has no in-place rename.
func resolveDistro(ctx context.Context, _ Env, opts Options) Options {
	if opts.Distro != "" && opts.Distro != "flashserver_ubuntu" {
		return opts
	}
	if wslNamedExists(ctx, "flashserver_ubuntu") {
		opts.Distro = "flashserver_ubuntu"
		return opts
	}
	if wslNamedExists(ctx, "Ubuntu") && wslNamedHasConfig(ctx, "Ubuntu", opts.ConfigPath) {
		opts.Distro = "Ubuntu"
		return opts
	}
	opts.Distro = "flashserver_ubuntu"
	return opts
}

func wslNamedExists(ctx context.Context, name string) bool {
	c, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return exec.CommandContext(c, sysExe("wsl.exe"), "-d", name, "-u", "root", "--", "true").Run() == nil
}

// wslDistroRegistered checks `wsl -l -q` without starting the distro.
func wslDistroRegistered(ctx context.Context, name string) bool {
	c, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, sysExe("wsl.exe"), "-l", "-q").Output()
	if err != nil {
		return false
	}
	text := strings.ToLower(string(normalizeDiagnostic(out)))
	return strings.Contains(text, strings.ToLower(name))
}

func wslNamedHasConfig(ctx context.Context, name, config string) bool {
	c, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return exec.CommandContext(c, sysExe("wsl.exe"), "-d", name, "-u", "root", "--", "test", "-f", config).Run() == nil
}

func writeDistroMarker(name string) {
	dir := WindowsStateDir()
	if dir == "" {
		return
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return
	}
	_ = os.WriteFile(filepath.Join(dir, "distro.txt"), []byte(name+"\n"), 0o644)
}

func ensureModelFirewall(ctx context.Context, i *installer) {
	rule := "FlashServer models"
	_ = exec.CommandContext(ctx, sysExe("netsh.exe"),
		"advfirewall", "firewall", "delete", "rule", "name="+rule).Run()
	cmd := exec.CommandContext(ctx, sysExe("netsh.exe"),
		"advfirewall", "firewall", "add", "rule", "name="+rule,
		"dir=in", "action=allow", "protocol=TCP", "localport=Any",
		"profile=private,domain")
	if err := cmd.Run(); err != nil {
		i.printf("warn: add Windows firewall rule: %v\n", err)
	}
}

func installWSL(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	writeDistroMarker(opts.Distro)
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
	if err := moveDistro(ctx, opts, &i); err != nil {
		return err
	}
	if err := cancellationErr(ctx, opts); err != nil {
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
		if err := copyToWSL(ctx, opts, resolveBinary(opts.BinDir, "flashserver", "linux", linuxArch), path.Join(binDir, "flashserver")); err != nil {
			return err
		}
		return installBundleSource(ctx, opts, &i)
	}); err != nil {
		return err
	}
	cfg, err := json.MarshalIndent(map[string]any{
		"addr":         exposedAddr(opts.Addr),
		"token":        opts.Token,
		"flashcli_bin": path.Join(binDir, "flashcli"),
		"public_host":  "localhost",
		"serve_host":   "0.0.0.0",
		"log_dir":      path.Join(opts.Home, "logs", "serve"),
		"max_loaded":   0,
	}, "", "  ")
	if err != nil {
		return err
	}
	if err := stepf(out, 5, total, "Writing configuration", func() error {
		if err := writeToWSL(ctx, opts, opts.ConfigPath, append(cfg, '\n'), 0o600); err != nil {
			return err
		}
		if err := writeToWSL(ctx, opts, path.Join(opts.Home, mirror.EnvFile), mirrorEnvContent(), 0o644); err != nil {
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
		if err := writeToWSL(ctx, opts, autostartMarker, []byte("enabled\n"), 0o644); err != nil {
			return err
		}
		ensureModelFirewall(ctx, &i)
		return nil
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

// stepf prints a friendly progress line and reports the outcome. The step is
// announced and completed on separate lines so the installer can show the
// detailed output that follows while the step is still running.
func stepf(out io.Writer, n, total int, name string, fn func() error) error {
	activeStep.mu.Lock()
	activeStep.name = name
	activeStep.since = time.Now()
	activeStep.mu.Unlock()
	fmt.Fprintf(out, "[%d/%d] %s ...\n", n, total, name)
	err := fn()
	activeStep.mu.Lock()
	activeStep.name = ""
	activeStep.mu.Unlock()
	if err != nil {
		fmt.Fprintf(out, "[%d/%d] %s ... FAILED\n", n, total, name)
		return err
	}
	fmt.Fprintf(out, "[%d/%d] %s ... ok\n", n, total, name)
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
	if wslDistroRegistered(ctx, opts.Distro) {
		// The name exists but the distro did not answer after the cold-start
		// retries. Try a clean terminate before giving up; never import the
		// same name (WSL returns a generic 0xffffffff).
		_ = exec.CommandContext(ctx, sysExe("wsl.exe"), "--terminate", opts.Distro).Run()
		time.Sleep(3 * time.Second)
		if err := wslRoot(ctx, opts, "true"); err == nil {
			return nil
		}
		return fmt.Errorf("WSL distro %q is registered but cannot start; run `wsl -d %s -u root true` to inspect it, or export/unregister it before reinstalling", opts.Distro, opts.Distro)
	}
	// flashserver_ubuntu is not a Microsoft Store distro name; import the
	// official Ubuntu rootfs directly under the dedicated name.
	if opts.Distro == "flashserver_ubuntu" {
		i.printf("\nimporting the Ubuntu rootfs as %s\n", opts.Distro)
		return importDistroRootfs(ctx, opts, i)
	}
	i.printf("\ninstalling Ubuntu with wsl --install (this may take up to 90 seconds)\n")
	installCtx, cancelInstall := context.WithTimeout(ctx, 90*time.Second)
	err := i.runDiag(installCtx, sysExe("wsl.exe"), "--install", "-d", opts.Distro, "--no-launch")
	cancelInstall()
	if err != nil {
		if !wslStatusOK(ctx) {
			return fmt.Errorf("%w: WSL2 must be restarted before %s can be used (%v)", ErrRebootRequired, opts.Distro, err)
		}
		// Store/GitHub downloads can hang with no traffic. Cap the wait and
		// fall back to the official Ubuntu cloud rootfs, imported directly.
		i.printf("\nwsl --install failed or timed out after 90 seconds (%v); importing the Ubuntu rootfs instead\n", err)
		if wslRoot(ctx, opts, "true") == nil {
			return nil
		}
		if ierr := importDistroRootfs(ctx, opts, i); ierr != nil {
			return fmt.Errorf("install WSL distro %s: %w (rootfs import: %v)", opts.Distro, err, ierr)
		}
		return nil
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
	i.printf("WSL distro %s did not become available; importing the Ubuntu rootfs instead\n", opts.Distro)
	if ierr := importDistroRootfs(ctx, opts, i); ierr != nil {
		return fmt.Errorf("WSL distro %s did not become available (rootfs import: %v)", opts.Distro, ierr)
	}
	return nil
}

const ubuntuRootfsName = "noble-server-cloudimg-amd64-root.tar.xz"

// ubuntuRootfsBases are tried in order; the first two are China mirrors.
var ubuntuRootfsBases = []string{
	"https://mirrors.tuna.tsinghua.edu.cn/ubuntu-cloud-images/noble/current",
	"https://mirrors.ustc.edu.cn/ubuntu-cloud-images/noble/current",
	"https://cloud-images.ubuntu.com/noble/current",
}

// importDistroRootfs registers the distro from an Ubuntu rootfs tarball. It is
// the fallback for networks where `wsl --install` cannot reach the Store or
// GitHub. WSL accepts the official .tar.xz directly.
func importDistroRootfs(ctx context.Context, opts Options, i *installer) error {
	target := strings.TrimSpace(opts.WSLDir)
	if target == "" {
		target = filepath.Join(os.Getenv("LOCALAPPDATA"), "wsl", opts.Distro)
	}
	abs, err := filepath.Abs(target)
	if err != nil {
		return fmt.Errorf("invalid WSL directory %q: %w", target, err)
	}
	registered, err := registeredForImport(ctx, i, opts.Distro)
	if err != nil {
		return fmt.Errorf("check WSL registration before import: %w", err)
	}
	if registered {
		return fmt.Errorf("WSL distro %q is already registered; refusing to overwrite it", opts.Distro)
	}
	if err := i.prepareWSLLocation(abs); err != nil {
		return err
	}
	rootfs := strings.TrimSpace(opts.DistroRootfs)
	cleanup := func() {}
	if rootfs == "" {
		path, done, err := downloadUbuntuRootfs(ctx, i)
		if err != nil {
			return err
		}
		rootfs, cleanup = path, done
	}
	defer cleanup()
	if err := cancellationErr(ctx, opts); err != nil {
		return err
	}
	i.printf("\nimport Ubuntu rootfs into %s\n", abs)
	// Let the import finish even if the UI requests cancellation. An interrupted
	// import can leave a partial VHDX that must never be overwritten on retry.
	i.printf("WSL_IMPORT_BEGIN %s; cancellation will wait for this command to finish\n", abs)
	importErr := i.runDiag(context.WithoutCancel(ctx), sysExe("wsl.exe"), "--import", opts.Distro, abs, rootfs, "--version", "2")
	i.printf("WSL_IMPORT_END %s; result=%v\n", abs, importErr)
	if cancelErr := cancellationErr(ctx, opts); cancelErr != nil {
		return cancelledImportState(ctx, cancelErr, opts.Distro, abs, i)
	}
	if err := importErr; err != nil {
		return fmt.Errorf("wsl --import %s: %w; existing target files were preserved for inspection", abs, err)
	}
	i.printf("imported WSL distro %s into %s (Ubuntu 24.04 rootfs)\n", opts.Distro, abs)
	return nil
}

func cancelledImportState(ctx context.Context, cancelErr error, name, target string, i *installer) error {
	checkCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancel()
	registered, err := registeredForImport(checkCtx, i, name)
	if err != nil {
		return fmt.Errorf("%w: WSL import command finished, but registration could not be checked: %v; inspect %s before retrying", cancelErr, err, target)
	}
	if !registered {
		return fmt.Errorf("%w: WSL import command finished without registering %s; inspect %s before retrying", cancelErr, name, target)
	}
	actual, err := distroBasePath(checkCtx, i, name)
	if err != nil {
		return fmt.Errorf("%w: WSL import command finished, but BasePath could not be checked: %v; inspect %s before retrying", cancelErr, err, target)
	}
	if err := verifyWSLLocation(name, actual, target, i); err != nil {
		return fmt.Errorf("%w: WSL import command finished, but storage verification failed: %v; manual inspection required", cancelErr, err)
	}
	return fmt.Errorf("%w: WSL import finished at %s; setup stopped before later steps", cancelErr, actual)
}

func registeredForImport(ctx context.Context, i *installer, name string) (bool, error) {
	output, err := i.runDiagOutput(ctx, sysExe("wsl.exe"), "--list", "--quiet")
	if err != nil {
		return false, err
	}
	for _, line := range strings.Split(string(normalizeDiagnostic(output)), "\n") {
		if strings.EqualFold(strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), "\uFEFF")), name) {
			return true, nil
		}
	}
	return false, nil
}

func (i *installer) prepareWSLLocation(path string) error {
	if i.prepareLocation != nil {
		return i.prepareLocation(path)
	}
	return prepareWSLLocation(path)
}

func prepareWSLLocation(abs string) error {
	info, err := os.Lstat(abs)
	if err == nil {
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("WSL target %s is not a regular directory", abs)
		}
		entries, readErr := os.ReadDir(abs)
		if readErr != nil {
			return fmt.Errorf("read WSL target %s: %w", abs, readErr)
		}
		if len(entries) != 0 {
			return fmt.Errorf("WSL target %s is not empty; refusing to overwrite it", abs)
		}
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("inspect WSL target %s: %w", abs, err)
	}
	if err := os.MkdirAll(abs, 0o755); err != nil {
		return fmt.Errorf("create WSL target %s: %w", abs, err)
	}
	probe, err := os.CreateTemp(abs, ".flashserver-write-check-*")
	if err != nil {
		return fmt.Errorf("WSL target %s is not writable: %w", abs, err)
	}
	name := probe.Name()
	if err := probe.Close(); err != nil {
		return fmt.Errorf("close WSL target write probe: %w", err)
	}
	if err := os.Remove(name); err != nil {
		return fmt.Errorf("remove WSL target write probe: %w", err)
	}
	return nil
}

func downloadUbuntuRootfs(ctx context.Context, i *installer) (string, func(), error) {
	dir, err := os.MkdirTemp("", "flashserver-ubuntu-rootfs-*")
	if err != nil {
		return "", nil, err
	}
	cleanup := func() { _ = os.RemoveAll(dir) }
	dest := filepath.Join(dir, ubuntuRootfsName)
	client := &http.Client{}
	var lastErr error
	for _, base := range ubuntuRootfsBases {
		url := strings.TrimRight(base, "/") + "/" + ubuntuRootfsName
		for attempt := 1; attempt <= 2; attempt++ {
			i.printf("\ndownload Ubuntu rootfs: %s\n", url)
			if err := fetchRootfs(ctx, client, url, dest, i); err == nil {
				return dest, cleanup, nil
			} else {
				lastErr = err
				i.printf("warn: download failed: %v\n", err)
			}
			select {
			case <-ctx.Done():
				cleanup()
				return "", nil, ctx.Err()
			case <-time.After(time.Second):
			}
		}
	}
	cleanup()
	return "", nil, fmt.Errorf("download Ubuntu rootfs: %w", lastErr)
}

func fetchRootfs(ctx context.Context, client *http.Client, url, dest string, i *installer) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "flashcli/"+version.Version)
	req.Header.Set("Accept", "*/*")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()
	total := resp.ContentLength
	var written, lastReport int64
	buf := make([]byte, 1<<20)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			written += int64(n)
			if total > 0 && written-lastReport >= 32<<20 {
				lastReport = written
				i.printf("download Ubuntu rootfs: %d/%d MiB\n", written>>20, total>>20)
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return rerr
		}
	}
	if total > 0 && written != total {
		return fmt.Errorf("incomplete download (%d/%d bytes)", written, total)
	}
	if written < 100<<20 {
		return fmt.Errorf("downloaded rootfs is too small (%d bytes)", written)
	}
	return nil
}

// moveDistro verifies the requested location. It never unregisters a distro.
func moveDistro(ctx context.Context, opts Options, i *installer) error {
	if strings.TrimSpace(opts.WSLDir) == "" {
		return nil
	}
	target, err := filepath.Abs(strings.TrimSpace(opts.WSLDir))
	if err != nil {
		return fmt.Errorf("invalid requested WSL directory: %w", err)
	}
	current, err := distroBasePath(ctx, i, opts.Distro)
	if err != nil {
		return fmt.Errorf("cannot verify current WSL storage for %s: %w", opts.Distro, err)
	}
	if equalWSLPath(current, target) {
		return verifyWSLLocation(opts.Distro, current, target, i)
	}
	if opts.Distro != "flashserver_ubuntu" {
		return fmt.Errorf("refusing to move legacy distribution %s automatically; current=%s requested=%s", opts.Distro, current, target)
	}
	if err := i.prepareWSLLocation(target); err != nil {
		return err
	}
	if err := cancellationErr(ctx, opts); err != nil {
		return err
	}
	if opts.DryRun {
		i.printf("$ wsl.exe --terminate %s; wsl.exe --manage %s --move %s\n", opts.Distro, opts.Distro, target)
		return nil
	}
	help, err := i.runDiagOutput(ctx, sysExe("wsl.exe"), "--help")
	if err != nil || !hasHelpOption(help, "--manage") || !hasHelpOption(help, "--move") {
		return fmt.Errorf("WSL CLI does not confirm --manage --move support; current=%s requested=%s", current, target)
	}
	if err := i.runDiag(ctx, sysExe("wsl.exe"), "--terminate", opts.Distro); err != nil {
		i.printf("warn: target-only terminate returned %v; trying the move without affecting other distributions\n", err)
	}
	if err := cancellationErr(ctx, opts); err != nil {
		return err
	}
	// A cancellation request must not kill wsl.exe while it is moving a VHDX.
	// The caller stops the remaining installation after this command returns.
	moveCtx := context.WithoutCancel(ctx)
	i.printf("WSL_MOVE_BEGIN %s -> %s; cancellation will wait for this command to finish\n", current, target)
	moveErr := i.runDiag(moveCtx, sysExe("wsl.exe"), "--manage", opts.Distro, "--move", target)
	i.printf("WSL_MOVE_END %s -> %s; result=%v\n", current, target, moveErr)
	if cancelErr := cancellationErr(ctx, opts); cancelErr != nil {
		return cancelledMoveState(ctx, cancelErr, opts.Distro, current, target, i)
	}
	if moveErr != nil {
		observed, queryErr := distroBasePath(ctx, i, opts.Distro)
		if queryErr != nil {
			return fmt.Errorf("target-only move failed (%v) and registration is uncertain: %w", moveErr, queryErr)
		}
		if equalWSLPath(observed, target) {
			return verifyWSLLocation(opts.Distro, observed, target, i)
		}
		if !equalWSLPath(observed, current) {
			return fmt.Errorf("target-only move failed and BasePath changed unexpectedly to %s; manual inspection required", observed)
		}
		entries, readErr := os.ReadDir(target)
		if readErr != nil {
			return fmt.Errorf("target-only move failed and destination cannot be inspected: %w", readErr)
		}
		if len(entries) > 0 {
			return fmt.Errorf("target-only move failed and destination contains files; manual inspection required: %s", target)
		}
		if !opts.AllowGlobalWSLShutdown {
			return fmt.Errorf("target-only WSL move failed (%v); current=%s requested=%s; global shutdown was not authorized", moveErr, current, target)
		}
		if err := cancellationErr(ctx, opts); err != nil {
			return err
		}
		i.printf("global WSL shutdown was explicitly authorized; stopping all WSL distributions before one move retry\n")
		if err := i.runDiag(moveCtx, sysExe("wsl.exe"), "--shutdown"); err != nil {
			return fmt.Errorf("authorized global WSL shutdown failed: %w", err)
		}
		if err := cancellationErr(ctx, opts); err != nil {
			return err
		}
		beforeRetry, err := distroBasePath(ctx, i, opts.Distro)
		if err != nil || !equalWSLPath(beforeRetry, current) {
			return fmt.Errorf("WSL registration changed before the authorized move retry: current=%s observed=%s query error=%v; manual inspection required", current, beforeRetry, err)
		}
		if err := i.prepareWSLLocation(target); err != nil {
			return fmt.Errorf("WSL target changed before the authorized move retry: %w", err)
		}
		if err := cancellationErr(ctx, opts); err != nil {
			return err
		}
		i.printf("WSL_MOVE_BEGIN %s -> %s; authorized retry; cancellation will wait for this command to finish\n", current, target)
		err = i.runDiag(moveCtx, sysExe("wsl.exe"), "--manage", opts.Distro, "--move", target)
		i.printf("WSL_MOVE_END %s -> %s; authorized retry result=%v\n", current, target, err)
		if cancelErr := cancellationErr(ctx, opts); cancelErr != nil {
			return cancelledMoveState(ctx, cancelErr, opts.Distro, current, target, i)
		}
		if err != nil {
			return fmt.Errorf("WSL move failed after authorized shutdown: %w; verify registered path before retrying", err)
		}
	}
	actual, err := distroBasePath(ctx, i, opts.Distro)
	if err != nil {
		return fmt.Errorf("WSL move returned success but registration could not be verified: %w", err)
	}
	return verifyWSLLocation(opts.Distro, actual, target, i)
}

func cancelledMoveState(ctx context.Context, cancelErr error, name, source, target string, i *installer) error {
	checkCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 15*time.Second)
	defer cancel()
	actual, err := distroBasePath(checkCtx, i, name)
	if err != nil {
		return fmt.Errorf("%w: WSL move command finished, but BasePath could not be checked: %v; manual inspection required", cancelErr, err)
	}
	if equalWSLPath(actual, target) {
		if err := verifyWSLLocation(name, actual, target, i); err != nil {
			return fmt.Errorf("%w: WSL move command finished at %s but storage verification failed: %v; manual inspection required", cancelErr, actual, err)
		}
		return fmt.Errorf("%w: WSL move finished at requested path %s; setup stopped before later steps", cancelErr, actual)
	}
	if equalWSLPath(actual, source) {
		return fmt.Errorf("%w: WSL move command finished; registered path remains %s; inspect destination %s before retrying", cancelErr, actual, target)
	}
	return fmt.Errorf("%w: WSL move command finished at unexpected path %s; manual inspection required", cancelErr, actual)
}

func distroBasePath(ctx context.Context, i *installer, name string) (string, error) {
	queryCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	script := "Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss' -ErrorAction Stop | Get-ItemProperty | Select-Object DistributionName,BasePath | ConvertTo-Json -Compress"
	output, err := i.runDiagOutput(queryCtx, sysExe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", script)
	if err != nil {
		return "", err
	}
	type registration struct {
		DistributionName string
		BasePath         string
	}
	var entries []registration
	if json.Unmarshal(output, &entries) != nil {
		var entry registration
		if err := json.Unmarshal(output, &entry); err != nil {
			return "", err
		}
		entries = []registration{entry}
	}
	for _, entry := range entries {
		if strings.EqualFold(entry.DistributionName, name) && entry.BasePath != "" {
			return entry.BasePath, nil
		}
	}
	return "", fmt.Errorf("registered BasePath for %s not found", name)
}

func equalWSLPath(a, b string) bool {
	clean := func(p string) string { return strings.TrimPrefix(filepath.Clean(p), `\\?\`) }
	return strings.EqualFold(clean(a), clean(b))
}
func verifyWSLLocation(name, actual, target string, i *installer) error {
	if !equalWSLPath(actual, target) {
		return fmt.Errorf("WSL storage mismatch for %s: actual=%s requested=%s", name, actual, target)
	}
	if _, err := os.Stat(filepath.Join(actual, "ext4.vhdx")); err != nil {
		return fmt.Errorf("WSL storage for %s reports %s but ext4.vhdx is not verified: %w", name, actual, err)
	}
	i.printf("verified WSL storage for %s: %s\n", name, actual)
	return nil
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

// installBundleSource installs the packaged flashcli-bundle source into WSL
// and points ~/.flashcli/install.env at it. This avoids requiring GitHub/git
// access from WSL when a bundle venv is created.
func installBundleSource(ctx context.Context, opts Options, i *installer) error {
	src := filepath.Join(opts.BinDir, "flashcli-bundle.tar.gz")
	if _, err := os.Stat(src); err != nil {
		i.printf("warn: %s not found; bundle venvs fall back to FLASHCLI_INSTALL_REPO\n", src)
		return nil
	}
	const destDir = "/usr/local/share/flashcli"
	tarPath := path.Join(destDir, "flashcli-bundle.tar.gz")
	if err := copyToWSL(ctx, opts, src, tarPath); err != nil {
		return err
	}
	extract := "mkdir -p " + shellQuote(destDir) + " && tar -xzf " + shellQuote(tarPath) + " -C " + shellQuote(destDir)
	if err := wslRoot(ctx, opts, "sh", "-c", extract); err != nil {
		return fmt.Errorf("extract flashcli-bundle: %w", err)
	}
	spec := destDir + "/flashcli-bundle[infer]"
	envFile := path.Join(opts.Home, "install.env")
	envLine := "FLASHCLI_BUNDLE_PIP_SPEC=" + spec
	merge := "mkdir -p " + shellQuote(path.Dir(envFile)) + " && { grep -v '^FLASHCLI_BUNDLE_PIP_SPEC=' " +
		shellQuote(envFile) + " 2>/dev/null || true; printf '%s\\n' " + shellQuote(envLine) +
		"; } > " + shellQuote(envFile+".tmp") + " && mv " + shellQuote(envFile+".tmp") + " " + shellQuote(envFile)
	if err := wslRoot(ctx, opts, "sh", "-c", merge); err != nil {
		return fmt.Errorf("write install.env: %w", err)
	}
	i.printf("bundled flashcli-bundle source: %s\n", spec)
	return nil
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
	out, err := cmd.CombinedOutput()
	if len(out) > 0 {
		_, _ = diag.Write(normalizeDiagnostic(out))
	}
	return err
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
	dir := WindowsStateDir()
	if dir == "" {
		return "", fmt.Errorf("LOCALAPPDATA is not set")
	}
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
	p := WindowsStatePath("api-url.txt")
	if p == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	return os.WriteFile(p, []byte(url+"\n"), 0o644)
}

// clientAPIURL returns the URL written by writeClientAPI (or the default).
func clientAPIURL() string {
	if p := WindowsStatePath("api-url.txt"); p != "" {
		if b, err := os.ReadFile(p); err == nil {
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
