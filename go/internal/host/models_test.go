package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEmptyCache(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	models, err := ListModels()
	if err != nil {
		t.Fatal(err)
	}
	if len(models) != 0 {
		t.Fatalf("models=%v", models)
	}
	areas := Storage()
	if len(areas) == 0 {
		t.Fatal("expected storage areas")
	}
}

func TestBundleServes(t *testing.T) {
	dir := t.TempDir()
	write := func(body string) {
		if err := os.WriteFile(filepath.Join(dir, "flashcli-bundle.json"), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"entry":{"run":{"module":"run"},"serve":{"module":"serve"}}}`)
	if !bundleServes(dir) {
		t.Fatal("top-level serve entry not detected")
	}
	write(`{"entry":{"run":{"module":"run"}}}`)
	if bundleServes(dir) {
		t.Fatal("run-only bundle reported as serve")
	}
	write(`{"environments":{"sm89-cu124-linux-x86_64-py312":{"entry":{"run":{},"serve":{}}}}}`)
	if !bundleServes(dir) {
		t.Fatal("environment serve entry not detected")
	}
	if bundleServes(filepath.Join(dir, "missing")) {
		t.Fatal("missing bundle reported as serve")
	}
}
