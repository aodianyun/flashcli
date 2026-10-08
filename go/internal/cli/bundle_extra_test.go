package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
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
