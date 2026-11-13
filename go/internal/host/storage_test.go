package host

import (
	"os"
	"path/filepath"
	"testing"
)

func writeStorageFixture(t *testing.T, home string) {
	t.Helper()
	for _, name := range []string{"cache", "python", "tools", "runtimes"} {
		path := filepath.Join(home, name, "payload.bin")
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, make([]byte, 4096), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestCleanSharedCaches(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	writeStorageFixture(t, home)

	freed, err := CleanSharedCaches([]string{"cache"})
	if err != nil {
		t.Fatal(err)
	}
	if freed <= 0 {
		t.Fatalf("freed = %d", freed)
	}
	for _, name := range []string{"cache", "python", "tools"} {
		if _, err := os.Stat(filepath.Join(home, name)); !os.IsNotExist(err) {
			t.Fatalf("%s still exists: %v", name, err)
		}
	}
	if _, err := os.Stat(filepath.Join(home, "runtimes")); err != nil {
		t.Fatalf("runtimes removed unexpectedly: %v", err)
	}
	if _, err := CleanSharedCaches([]string{"runtimes"}); err == nil {
		t.Fatal("runtimes are model data and must use RemoveCachedRef")
	}
	if _, err := CleanSharedCaches([]string{"all"}); err == nil {
		t.Fatal("all is not a shared-cache target")
	}
	if _, err := CleanSharedCaches([]string{"unknown"}); err == nil {
		t.Fatal("expected unknown target error")
	}
	if _, err := CleanSharedCaches(nil); err == nil {
		t.Fatal("expected empty target error")
	}
}

func TestStorageGroupsCacheAreas(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	writeStorageFixture(t, home)

	var cacheBytes int64
	names := map[string]bool{}
	for _, area := range Storage() {
		names[area.Name] = true
		if area.Name == "cache" {
			cacheBytes = area.Bytes
		}
	}
	for _, want := range []string{"bundles", "models", "runtimes", "cache"} {
		if !names[want] {
			t.Fatalf("missing %s in %v", want, names)
		}
	}
	for _, hidden := range []string{"python", "tools"} {
		if names[hidden] {
			t.Fatalf("%s must be grouped into cache, got %v", hidden, names)
		}
	}
	if cacheBytes < 3*4096 {
		t.Fatalf("cache group bytes = %d, want cache+python+tools", cacheBytes)
	}
}
