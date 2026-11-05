package system

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// AutoInstallEnabled reports whether root-level automatic capability install is
// enabled. Non-root users never auto-install.
func AutoInstallEnabled() bool {
	if os.Geteuid() != 0 {
		return false
	}
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_AUTO_INSTALL_SYSTEM"))) {
	case "never", "0", "false", "no", "off":
		return false
	case "auto", "always", "1", "true", "yes", "on", "":
		return true
	default:
		return false
	}
}

// Install installs the packages needed for missing capabilities.
func Install(ctx context.Context, missing []Capability, abi string, quiet bool) error {
	if len(missing) == 0 {
		return nil
	}
	if os.Geteuid() != 0 {
		return fmt.Errorf("system package installation requires root; run the install command as root or install manually")
	}
	mgr, err := DetectManager()
	if err != nil {
		return err
	}
	pkgs := map[string]bool{}
	for _, cap := range missing {
		for _, pkg := range PackagesFor(mgr, cap, abi) {
			pkgs[pkg] = true
		}
	}
	if len(pkgs) == 0 {
		return fmt.Errorf("no package mapping for missing capabilities")
	}
	args := make([]string, 0, len(pkgs))
	for pkg := range pkgs {
		args = append(args, pkg)
	}
	if mgr == APT {
		update := exec.CommandContext(ctx, "apt-get", "update", "-qq")
		update.Env = append(os.Environ(), "DEBIAN_FRONTEND=noninteractive")
		if quiet {
			update.Stdout = nil
			update.Stderr = nil
		} else {
			update.Stdout = os.Stdout
			update.Stderr = os.Stderr
		}
		if err := update.Run(); err != nil {
			return fmt.Errorf("apt-get update failed: %w", err)
		}
	}
	argv := installArgv(mgr, args)
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = os.Environ()
	if mgr == APT {
		cmd.Env = append(cmd.Env, "DEBIAN_FRONTEND=noninteractive")
	}
	if quiet {
		cmd.Stdout = nil
		cmd.Stderr = nil
	} else {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s failed: %w", strings.Join(argv, " "), err)
	}
	return nil
}

// InstallBinutils installs the host ELF inspector used by native preflight.
// The caller must enforce the auto-install policy before calling.
func InstallBinutils(ctx context.Context, quiet bool) error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("system package installation requires root; install binutils manually")
	}
	mgr, err := DetectManager()
	if err != nil {
		return err
	}
	packages := []string{"binutils"}
	if mgr == APK {
		packages = []string{"binutils"}
	}
	if mgr == APT {
		update := exec.CommandContext(ctx, "apt-get", "update", "-qq")
		update.Env = append(os.Environ(), "DEBIAN_FRONTEND=noninteractive")
		if quiet {
			update.Stdout = nil
			update.Stderr = nil
		} else {
			update.Stdout = os.Stdout
			update.Stderr = os.Stderr
		}
		if err := update.Run(); err != nil {
			return fmt.Errorf("apt-get update failed: %w", err)
		}
	}
	argv := installArgv(mgr, packages)
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = os.Environ()
	if mgr == APT {
		cmd.Env = append(cmd.Env, "DEBIAN_FRONTEND=noninteractive")
	}
	if quiet {
		cmd.Stdout = nil
		cmd.Stderr = nil
	} else {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s failed: %w", strings.Join(argv, " "), err)
	}
	return nil
}

// BinutilsHint returns the distro package hint for the ELF inspector.
func BinutilsHint() string { return "binutils" }

func installArgv(mgr Manager, packages []string) []string {
	switch mgr {
	case APT:
		return append([]string{"apt-get", "install", "-y"}, packages...)
	case DNF:
		return append([]string{"dnf", "install", "-y"}, packages...)
	case YUM:
		return append([]string{"yum", "install", "-y"}, packages...)
	case APK:
		return append([]string{"apk", "add", "--no-cache"}, packages...)
	case ZYPPER:
		return append([]string{"zypper", "--non-interactive", "install"}, packages...)
	default:
		return nil
	}
}
