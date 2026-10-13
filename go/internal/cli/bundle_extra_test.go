package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

func writeBundle(t *testing.T, root string) {
	t.Helper()
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": 3, "protocol_version": 1,
		"name": "demo", "python_abi": "310",
		"entry":   map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{"sm89-cu124-linux-x86_64-py310": "runtime/x"},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, "flashcli-bundle.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "run.py"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestBundleCleanRemovesRuntimes(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	runtimes := filepath.Join(home, "runtimes")
	if err := os.MkdirAll(filepath.Join(runtimes, "x-local-abc"), 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	if _, err := os.Stat(runtimes); err == nil {
		t.Fatal("runtimes dir should be removed")
	}
}

func TestModelsShowLocal(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle := filepath.Join(home, "demo")
	if err := os.MkdirAll(bundle, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundle)
	if code := Main([]string{"models", "show", bundle}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
}

func writeRuntimeMarker(t *testing.T, id, preset string) string {
	t.Helper()
	dir := filepath.Join(paths.Runtimes(), id)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(map[string]any{"preset": preset, "runtime_id": id})
	if err := os.WriteFile(filepath.Join(dir, ".runtime.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func mustStat(t *testing.T, path string, wantExist bool) {
	t.Helper()
	_, err := os.Stat(path)
	if (err == nil) != wantExist {
		t.Fatalf("stat %s: exists=%v want %v", path, err == nil, wantExist)
	}
}

func TestBundleCleanAll(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if err := os.MkdirAll(paths.Runtimes(), 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--all"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, paths.Runtimes(), false)
}

func TestBundleCleanByRef(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	keep := writeRuntimeMarker(t, "other-local-1", "other")
	drop := writeRuntimeMarker(t, "pi05-local-1", "pi05_libero")
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/pi05_libero:1.0.0"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, drop, false)
	mustStat(t, keep, true)
}

func TestBundleCleanByRefNoMatch(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/none:1.0.0"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
}

func TestBundleCleanFull(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	for _, d := range []string{paths.Runtimes(), paths.Models(), paths.Bundles()} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	repoIndex := filepath.Join(paths.Cache(), "repo-index")
	if err := os.MkdirAll(repoIndex, 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--full"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, paths.Runtimes(), false)
	mustStat(t, paths.Models(), false)
	mustStat(t, paths.Bundles(), false)
	mustStat(t, repoIndex, true) // --flashhub-cache not set

	if err := os.MkdirAll(repoIndex, 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--full", "--flashhub-cache"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, repoIndex, false)
}
