package setup

import (
	"os"
	"path/filepath"
)

// Windows keeps its per-user state (client settings, the WSL distro marker and
// the setup log) under %LOCALAPPDATA%. Earlier releases used the "FlashServer"
// directory; rename it once so an upgrade keeps the existing state.
const (
	windowsStateDirName       = "flashcli-desktop"
	legacyWindowsStateDirName = "FlashServer"
)

// WindowsStateDir returns %LOCALAPPDATA%\flashcli-desktop, migrating the
// legacy directory on first use. It returns "" when LOCALAPPDATA is unset.
func WindowsStateDir() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		return ""
	}
	dir := filepath.Join(base, windowsStateDirName)
	if _, err := os.Stat(dir); err == nil {
		return dir
	}
	legacy := filepath.Join(base, legacyWindowsStateDirName)
	if _, err := os.Stat(legacy); err != nil {
		return dir
	}
	if err := os.Rename(legacy, dir); err != nil {
		// A running client or an open setup log can hold a handle on the old
		// directory; keep using it so this run still works. The next run
		// retries the rename.
		return legacy
	}
	return dir
}

// WindowsStatePath joins parts under WindowsStateDir. It returns "" when
// LOCALAPPDATA is unset.
func WindowsStatePath(parts ...string) string {
	dir := WindowsStateDir()
	if dir == "" {
		return ""
	}
	return filepath.Join(append([]string{dir}, parts...)...)
}
