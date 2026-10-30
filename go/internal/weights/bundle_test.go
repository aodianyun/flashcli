package weights

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

// The remote cache key must come from the FlashHub repo name (the synced tree's
// parent dir), never from the manifest `name` (descriptive only).
func TestCacheKeyForRemoteUsesRepoName(t *testing.T) {
	root := filepath.Join(paths.Bundles(), "repo-name", "1.2.3")
	m := &manifest.Manifest{Name: "manifest-name", Root: root}
	if got, want := CacheKeyFor(m, "1.2.3"), "repo-name/1.2.3"; got != want {
		t.Fatalf("CacheKeyFor=%q want %q", got, want)
	}
}

func TestCacheKeyForLocalUsesLocalID(t *testing.T) {
	root := filepath.Join(t.TempDir(), "somebundle")
	m := &manifest.Manifest{Name: "somebundle", Root: root}
	want := runtime.IDFromPath(root, "somebundle") + "/local"
	if got := CacheKeyFor(m, "local"); got != want {
		t.Fatalf("CacheKeyFor=%q want %q", got, want)
	}
}

// The cache base key is variant-independent: it must never contain "@variant"
// (the variant only selects weights_dir / runtime cell).
func TestCacheKeyForIsVariantIndependent(t *testing.T) {
	root := filepath.Join(paths.Bundles(), "qwen_nvfp4", "1.0.1")
	m := &manifest.Manifest{Name: "qwen_nvfp4", Root: root}
	got := CacheKeyFor(m, "1.0.1")
	if got != "qwen_nvfp4/1.0.1" {
		t.Fatalf("CacheKeyFor=%q want qwen_nvfp4/1.0.1", got)
	}
	if strings.Contains(got, "@") {
		t.Fatalf("cache key must not contain @variant: %q", got)
	}
}

func TestManifestSpecsV4DefaultWeightsRoot(t *testing.T) {
	m := &manifest.Manifest{FormatVersion: 4, Raw: map[string]any{}}
	_, rel, _, err := ManifestSpecs(m, "")
	if err != nil {
		t.Fatal(err)
	}
	if rel != "" {
		t.Fatalf("v4 default rel = %q, want empty (store root)", rel)
	}
}

func TestManifestSpecsV4ExplicitWeightsDir(t *testing.T) {
	m := &manifest.Manifest{FormatVersion: 4, Raw: map[string]any{"weights_dir": "checkpoint"}}
	_, rel, _, err := ManifestSpecs(m, "")
	if err != nil {
		t.Fatal(err)
	}
	if rel != "checkpoint" {
		t.Fatalf("v4 explicit rel = %q", rel)
	}
}

func TestManifestSpecsV4ExtraWeightsDir(t *testing.T) {
	m := &manifest.Manifest{
		FormatVersion: 4,
		Raw: map[string]any{
			"weights": map[string]any{"source": "huggingface", "repo": "org/demo", "revision": "main"},
			"extra_weights": map[string]any{
				"tokenizer": map[string]any{"source": "huggingface", "repo": "org/tok", "revision": "main"},
			},
		},
	}
	_, _, extra, err := ManifestSpecs(m, "")
	if err != nil {
		t.Fatal(err)
	}
	if got := extra["tokenizer"].WeightsDir; got != "extra/tokenizer" {
		t.Fatalf("extra weights_dir=%q", got)
	}
	if got := ExtraWeightDest("/store", "", "tokenizer", extra["tokenizer"]); got != "/store/extra/tokenizer" {
		t.Fatalf("dest=%q", got)
	}
}

func TestStoreKeyForV4Readable(t *testing.T) {
	m := &manifest.Manifest{FormatVersion: 4, Name: "demo", Raw: map[string]any{
		"weights": map[string]any{"source": "huggingface", "repo": "org/model", "revision": "main"},
	}}
	got := StoreKeyFor(m, "1.0.0")
	if !strings.HasPrefix(got, "store/huggingface/org__model@main-") {
		t.Fatalf("store key=%q", got)
	}
	if got != StoreKeyFor(m, "1.0.1") {
		t.Fatal("weight store key must be version-independent")
	}
}
