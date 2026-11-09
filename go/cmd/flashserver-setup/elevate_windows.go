//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// ensureElevated relaunches the current command with UAC when service control
// is requested from a non-elevated shell (e.g. a Start Menu shortcut).
func ensureElevated() bool {
	if isAdmin() {
		return false
	}
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	args := strings.Join(os.Args[1:], " ")
	script := fmt.Sprintf("Start-Process -Verb RunAs -FilePath %q -ArgumentList %q", exe, args)
	if err := exec.Command("powershell.exe", "-NoProfile", "-Command", script).Run(); err != nil {
		return false
	}
	return true
}

func isAdmin() bool {
	return exec.Command("fltmc.exe").Run() == nil
}
