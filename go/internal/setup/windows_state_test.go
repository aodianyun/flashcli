package setup

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWindowsStateDirMigratesLegacy(t *testing.T) {
	base := t.TempDir()
	t.Setenv("LOCALAPPDATA", base)

	legacy := filepath.Join(base, legacyWindowsStateDirName)
	if err := os.MkdirAll(legacy, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(legacy, "settings.json"), []byte("{}\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	dir := WindowsStateDir()
	want := filepath.Join(base, windowsStateDirName)
	if dir != want {
		t.Fatalf("WindowsStateDir = %q, want %q", dir, want)
	}
	if _, err := os.Stat(legacy); !os.IsNotExist(err) {
		t.Fatalf("legacy directory still exists: %v", err)
	}
	blob, err := os.ReadFile(filepath.Join(dir, "settings.json"))
	if err != nil || string(blob) != "{}\n" {
		t.Fatalf("migrated settings.json = %q, %v", blob, err)
	}
}

func TestWindowsStateDirKeepsNewDirectory(t *testing.T) {
	base := t.TempDir()
	t.Setenv("LOCALAPPDATA", base)

	newDir := filepath.Join(base, windowsStateDirName)
	legacy := filepath.Join(base, legacyWindowsStateDirName)
	if err := os.MkdirAll(newDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(legacy, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(newDir, "distro.txt"), []byte("flashserver_ubuntu\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	if got := WindowsStateDir(); got != newDir {
		t.Fatalf("WindowsStateDir = %q, want %q", got, newDir)
	}
	if _, err := os.Stat(filepath.Join(legacy, "distro.txt")); !os.IsNotExist(err) {
		t.Fatalf("legacy directory was merged: %v", err)
	}
}

func TestWindowsStatePathWithoutLocalAppData(t *testing.T) {
	t.Setenv("LOCALAPPDATA", "")
	if got := WindowsStatePath("api-url.txt"); got != "" {
		t.Fatalf("WindowsStatePath = %q, want empty", got)
	}
}
