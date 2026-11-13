// Package setup installs and configures flashserver.
package setup

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"time"
)

// Env is the detected installation environment.
type Env struct {
	OS   string
	Arch string
	WSL  bool
}

// Step is one installation action shown by --dry-run.
type Step struct {
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Command     []string `json:"command,omitempty"`
}

// Detect inspects the current host.
func Detect(ctx context.Context) Env {
	env := Env{OS: runtime.GOOS, Arch: runtime.GOARCH}
	if env.OS == "windows" {
		c, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		env.WSL = exec.CommandContext(c, sysExe("wsl.exe"), "--status").Run() == nil
	}
	return env
}

// EffectiveBackend resolves auto to the platform default.
func EffectiveBackend(env Env, requested string) string {
	if requested != "" && requested != "auto" {
		return requested
	}
	if env.OS == "windows" {
		return "wsl"
	}
	return "native"
}

// Plan returns the ordered installation plan for env and backend.
func Plan(env Env, backend string) ([]Step, error) {
	backend = EffectiveBackend(env, backend)
	switch backend {
	case "native":
		if env.OS != "linux" {
			return nil, fmt.Errorf("native backend is only available on Linux")
		}
		return []Step{
			{Name: "install", Description: "install flashcli and flashserver binaries"},
			{Name: "configure", Description: "write flashserver config and local token"},
			{Name: "service", Description: "install flashserver systemd service"},
			{Name: "start", Description: "enable and start flashserver"},
			{Name: "health", Description: "check local flashserver health"},
		}, nil
	case "wsl":
		if env.OS != "windows" {
			return nil, fmt.Errorf("wsl backend is only available on Windows")
		}
		return []Step{
			{Name: "check-wsl2", Description: "check WSL2 availability"},
			{Name: "ensure-distro", Description: "ensure the Ubuntu WSL distribution", Command: []string{"wsl.exe", "--install", "-d", "Ubuntu", "--no-launch"}},
			{Name: "install", Description: "install flashcli and flashserver inside WSL"},
			{Name: "configure", Description: "write flashserver config and systemd inside WSL"},
			{Name: "start", Description: "enable and start flashserver inside WSL"},
			{Name: "startup", Description: "create a Windows logon task for WSL"},
			{Name: "health", Description: "check flashserver health via localhost"},
		}, nil
	default:
		return nil, fmt.Errorf("unknown backend %q (use auto, native, or wsl)", backend)
	}
}

func executableDir() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return executableDirOf(exe)
}
