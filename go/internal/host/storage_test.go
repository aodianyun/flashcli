package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCleanSharedCaches(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	targets := map[string]string{
		"cache":    filepath.Join(home, "cache", "downloads", "file"),
		"python":   filepath.Join(home, "python", "bin", "python3"),
		"tools":    filepath.Join(home, "tools", "uv", "uv"),
		"runtimes": filepath.Join(home, "runtimes", "runtime", "torch.so"),
	}
	for _, path := range targets {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, make([]byte, 4096), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	freed, err := CleanSharedCaches([]string{"cache", "tools"})
	if err != nil {
		t.Fatal(err)
	}
	if freed <= 0 {
		t.Fatalf("freed = %d", freed)
	}
	for _, name := range []string{"cache", "tools"} {
		if _, err := os.Stat(filepath.Join(home, name)); !os.IsNotExist(err) {
			t.Fatalf("%s still exists: %v", name, err)
		}
	}
	for _, name := range []string{"python", "runtimes"} {
		if _, err := os.Stat(filepath.Join(home, name)); err != nil {
			t.Fatalf("%s removed unexpectedly: %v", name, err)
		}
	}
	if _, err := CleanSharedCaches([]string{"unknown"}); err == nil {
		t.Fatal("expected unknown target error")
	}
	if _, err := CleanSharedCaches(nil); err == nil {
		t.Fatal("expected empty target error")
	}
}
