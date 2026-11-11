package host

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

func TestRefPathsKeepsSharedWeightsAndRuntime(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	rootA := writeTestMarker(t, "a/1.0.0", "a:1.0.0", "shared/weights")
	rootB := writeTestMarker(t, "b/1.0.0", "b:1.0.0", "shared/weights")
	sharedRuntime := "shared-runtime"
	if err := runtime.WriteMarker(sharedRuntime, map[string]any{"runtime_id": sharedRuntime, "bundle_root": rootA}); err != nil {
		t.Fatal(err)
	}
	for _, root := range []string{rootA, rootB} {
		rewriteMarker(t, root, map[string]any{"runtime_id": sharedRuntime})
	}
	weightsDir := filepath.Join(paths.Models(), "shared", "weights")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("weights-data"), 0o644); err != nil {
		t.Fatal(err)
	}
	runtimeDir := runtime.Dir(sharedRuntime)
	if err := os.WriteFile(filepath.Join(runtimeDir, "torch.bin"), make([]byte, 4096), 0o644); err != nil {
		t.Fatal(err)
	}

	got := map[string]bool{}
	for _, path := range RefPaths("a:1.0.0", true) {
		got[path] = true
	}
	if !got[rootA] {
		t.Fatalf("bundle path missing from %v", got)
	}
	if got[weightsDir] {
		t.Fatalf("shared weights path must be kept: %v", got)
	}
	if got[runtimeDir] {
		t.Fatalf("shared runtime path must be kept: %v", got)
	}

	res, err := RemoveCachedRef("a:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if !res.SharedWeights {
		t.Fatalf("expected shared_weights, got %+v", res)
	}
	if _, err := os.Stat(weightsDir); err != nil {
		t.Fatalf("shared weights removed: %v", err)
	}
	if _, err := os.Stat(runtimeDir); err != nil {
		t.Fatalf("shared runtime removed: %v", err)
	}
}
