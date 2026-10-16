package weights

import (
	"path/filepath"
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
