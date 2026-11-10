//go:build linux

package host

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

func TestDirUsageDedupesHardlinks(t *testing.T) {
	dir := t.TempDir()
	first := filepath.Join(dir, "weights.bin")
	if err := os.WriteFile(first, make([]byte, 8192), 0o644); err != nil {
		t.Fatal(err)
	}
	second := filepath.Join(dir, "hardlink.bin")
	if err := os.Link(first, second); err != nil {
		t.Skipf("hardlink unavailable: %v", err)
	}
	info, err := os.Stat(first)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := dirUsage(dir, map[fileKey]bool{}), allocatedBytes(info); got != want {
		t.Fatalf("usage = %d, want one inode = %d", got, want)
	}
}

func TestStorageDedupesAcrossAreas(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	if err := os.MkdirAll(paths.Runtimes(), 0o755); err != nil {
		t.Fatal(err)
	}
	cache := filepath.Join(home, "cache")
	if err := os.MkdirAll(cache, 0o755); err != nil {
		t.Fatal(err)
	}
	first := filepath.Join(paths.Runtimes(), "torch.bin")
	if err := os.WriteFile(first, make([]byte, 16384), 0o644); err != nil {
		t.Fatal(err)
	}
	second := filepath.Join(cache, "torch.bin")
	if err := os.Link(first, second); err != nil {
		t.Skipf("hardlink unavailable: %v", err)
	}
	info, err := os.Stat(first)
	if err != nil {
		t.Fatal(err)
	}
	var got int64
	for _, area := range Storage() {
		if area.Name == "runtimes" || area.Name == "cache" {
			got += area.Bytes
		}
	}
	if want := allocatedBytes(info); got != want {
		t.Fatalf("runtimes+cache = %d, want %d", got, want)
	}
}
