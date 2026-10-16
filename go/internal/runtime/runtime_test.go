package runtime

import (
	"os"
	"path/filepath"
	"testing"
)

// The local bundle id must canonicalize the path (resolve symlinks) so it
// matches flashcli_bundle.preset_ref.local_bundle_id.
func TestIDFromPathResolvesSymlinks(t *testing.T) {
	dir := t.TempDir()
	real := filepath.Join(dir, "real")
	if err := os.MkdirAll(real, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(real, link); err != nil {
		t.Skipf("symlink unsupported: %v", err)
	}
	if IDFromPath(link, "b") != IDFromPath(real, "b") {
		t.Fatalf("symlink id %q != real id %q", IDFromPath(link, "b"), IDFromPath(real, "b"))
	}
	if got, want := IDFromPath(real, "b"), "b-local-"+digest(canonicalPath(real)); got != want {
		t.Fatalf("IDFromPath=%q want %q", got, want)
	}
}
