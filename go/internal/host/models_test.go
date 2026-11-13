package host

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
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
	write(`{"defaults":{"entry":{"run":{"module":"run"}}}}`)
	if bundleServes(dir) {
		t.Fatal("run-only defaults.entry reported as serve")
	}
	write(`{"defaults":{"entry":{"run":{"module":"run"},"serve":{"module":"serve"}}}}`)
	if !bundleServes(dir) {
		t.Fatal("defaults.entry serve entry not detected")
	}
	write(`{"environments":{"sm89-cu124-linux-x86_64-py312":{"entry":{"run":{},"serve":{}}}}}`)
	if !bundleServes(dir) {
		t.Fatal("environment serve entry not detected")
	}
	if bundleServes(filepath.Join(dir, "missing")) {
		t.Fatal("missing bundle reported as serve")
	}
}

func rewriteMarker(t *testing.T, bundleDir string, edit map[string]any) {
	t.Helper()
	path := filepath.Join(bundleDir, flashhub.MarkerName)
	blob, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var marker map[string]any
	if err := json.Unmarshal(blob, &marker); err != nil {
		t.Fatal(err)
	}
	for key, value := range edit {
		marker[key] = value
	}
	blob, err = json.Marshal(marker)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, blob, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestListModelsReportsRuntimePerBundle(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	bundleDir := writeTestMarker(t, "demo/1", "demo:1", "demo/1")
	weightsDir := filepath.Join(paths.Models(), "demo", "1")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("weights-data"), 0o644); err != nil {
		t.Fatal(err)
	}

	runtimeID := "demo-1-runtime"
	if err := runtime.WriteMarker(runtimeID, map[string]any{"runtime_id": runtimeID, "bundle_root": bundleDir}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runtime.Dir(runtimeID), "torch.bin"), make([]byte, 4096), 0o644); err != nil {
		t.Fatal(err)
	}
	rewriteMarker(t, bundleDir, map[string]any{"runtime_id": runtimeID})

	models, err := ListModels()
	if err != nil {
		t.Fatal(err)
	}
	if len(models) != 1 {
		t.Fatalf("models = %+v", models)
	}
	got := models[0]
	if got.RuntimeID != runtimeID {
		t.Fatalf("runtime_id = %q, want %q", got.RuntimeID, runtimeID)
	}
	if got.RuntimeBytes < 4096 {
		t.Fatalf("runtime_bytes = %d, want >= 4096", got.RuntimeBytes)
	}
	if got.BundleBytes <= 0 || got.WeightsBytes <= 0 {
		t.Fatalf("bundle/weights bytes = %d/%d", got.BundleBytes, got.WeightsBytes)
	}
}

func TestListModelsFindsRuntimeByBundleRoot(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	bundleDir := writeTestMarker(t, "legacy/1", "legacy:1", "legacy/1")
	runtimeID := "legacy-1-runtime"
	if err := runtime.WriteMarker(runtimeID, map[string]any{"bundle_root": bundleDir}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runtime.Dir(runtimeID), "torch.bin"), make([]byte, 2048), 0o644); err != nil {
		t.Fatal(err)
	}

	models, err := ListModels()
	if err != nil {
		t.Fatal(err)
	}
	if len(models) != 1 {
		t.Fatalf("models = %+v", models)
	}
	if models[0].RuntimeID != runtimeID {
		t.Fatalf("runtime_id = %q, want %q", models[0].RuntimeID, runtimeID)
	}
	if models[0].RuntimeBytes < 2048 {
		t.Fatalf("runtime_bytes = %d, want >= 2048", models[0].RuntimeBytes)
	}
}
