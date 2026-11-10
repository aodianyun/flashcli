package host

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

func writeTestMarker(t *testing.T, key, ref, weightsKey string) string {
	t.Helper()
	dir := filepath.Join(paths.Bundles(), filepath.FromSlash(key))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := map[string]any{
		"ref":         ref,
		"cache_key":   key,
		"bundle_root": dir,
		"weights_key": weightsKey,
	}
	blob, err := json.Marshal(marker)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, flashhub.MarkerName), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "payload.bin"), []byte("bundle-data"), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestRemoveCachedRef(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	bundleDir := writeTestMarker(t, "demo/1", "demo:1", "demo/1")
	weightsDir := filepath.Join(paths.Models(), "demo", "1")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("weights-data"), 0o644); err != nil {
		t.Fatal(err)
	}

	res, err := RemoveCachedRef("demo:1")
	if err != nil {
		t.Fatal(err)
	}
	if !res.Removed || res.FreedBytes <= 0 {
		t.Fatalf("res = %+v", res)
	}
	if _, err := os.Stat(bundleDir); !os.IsNotExist(err) {
		t.Fatalf("bundle dir still exists: %v", err)
	}
	if _, err := os.Stat(weightsDir); !os.IsNotExist(err) {
		t.Fatalf("weights dir still exists: %v", err)
	}
	if _, err := RemoveCachedRef("demo:1"); err == nil {
		t.Fatal("expected missing-ref error")
	}
}

func TestRemoveCachedRefKeepsSharedWeights(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	firstBundle := writeTestMarker(t, "demo/1", "demo:1", "shared/weights")
	writeTestMarker(t, "demo/2", "demo:2", "shared/weights")
	weightsDir := filepath.Join(paths.Models(), "shared", "weights")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("weights-data"), 0o644); err != nil {
		t.Fatal(err)
	}

	res, err := RemoveCachedRef("demo:1")
	if err != nil {
		t.Fatal(err)
	}
	if !res.SharedWeights {
		t.Fatalf("expected shared weights, got %+v", res)
	}
	if _, err := os.Stat(firstBundle); !os.IsNotExist(err) {
		t.Fatalf("bundle dir still exists: %v", err)
	}
	if _, err := os.Stat(weightsDir); err != nil {
		t.Fatalf("shared weights removed: %v", err)
	}

	if _, err := RemoveCachedRef("demo:2"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(weightsDir); !os.IsNotExist(err) {
		t.Fatalf("weights dir still exists: %v", err)
	}
}
