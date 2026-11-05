package system

import (
	"fmt"
	"os/exec"
	"runtime"
	"strings"
)

// Manager is a supported host package manager.
type Manager string

const (
	APT    Manager = "apt"
	DNF    Manager = "dnf"
	YUM    Manager = "yum"
	APK    Manager = "apk"
	ZYPPER Manager = "zypper"
)

// DetectManager returns the available package manager.
func DetectManager() (Manager, error) {
	for _, item := range []struct {
		bin string
		mgr Manager
	}{
		{"apt-get", APT},
		{"dnf", DNF},
		{"yum", YUM},
		{"apk", APK},
		{"zypper", ZYPPER},
	} {
		if _, err := exec.LookPath(item.bin); err == nil {
			return item.mgr, nil
		}
	}
	return "", fmt.Errorf("no supported system package manager found (apt-get/dnf/yum/apk/zypper)")
}

// PackagesFor maps a capability to packages for a manager/ABI.
func PackagesFor(mgr Manager, cap Capability, abi string) []string {
	py := "python3"
	if len(abi) == 3 {
		py = "python3." + abi[1:]
	}
	switch mgr {
	case APT:
		switch cap {
		case CCompiler:
			return []string{"gcc", "libc6-dev"}
		case CXXCompiler:
			return []string{"g++"}
		case PythonHeaders:
			return []string{py + "-dev"}
		}
	case DNF, YUM:
		switch cap {
		case CCompiler:
			return []string{"gcc", "glibc-devel"}
		case CXXCompiler:
			return []string{"gcc-c++"}
		case PythonHeaders:
			return []string{py + "-devel"}
		}
	case APK:
		switch cap {
		case CCompiler:
			return []string{"gcc", "musl-dev"}
		case CXXCompiler:
			return []string{"g++"}
		case PythonHeaders:
			return []string{"python3-dev"}
		}
	case ZYPPER:
		switch cap {
		case CCompiler:
			return []string{"gcc", "glibc-devel"}
		case CXXCompiler:
			return []string{"gcc-c++"}
		case PythonHeaders:
			return []string{strings.ReplaceAll(py, "python3.", "python3") + "-devel"}
		}
	}
	return nil
}

// PackageHint returns a human-readable package hint for a capability.
func PackageHint(cap Capability, abi string) string {
	mgr, err := DetectManager()
	if err == nil {
		if pkgs := PackagesFor(mgr, cap, abi); len(pkgs) > 0 {
			return strings.Join(pkgs, " ")
		}
	}
	switch cap {
	case CCompiler:
		return "build-essential / gcc + libc6-dev"
	case CXXCompiler:
		return "g++ / gcc-c++"
	case PythonHeaders:
		if len(abi) == 3 {
			return fmt.Sprintf("python3.%s-dev (or the matching -devel package)", abi[1:])
		}
		return "matching python3-dev package"
	}
	return ""
}

// CurrentGOOS is exposed for deterministic diagnostics/tests.
func CurrentGOOS() string { return runtime.GOOS }
