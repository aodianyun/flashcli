package runtime

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestIDFromPathDeterministic(t *testing.T) {
	a := IDFromPath("/tmp/bundles/pi05", "pi05_libero")
	b := IDFromPath("/tmp/bundles/pi05", "pi05_libero")
	if a != b {
		t.Fatalf("not deterministic: %s vs %s", a, b)
	}
	if !strings.HasPrefix(a, "pi05_libero-local-") || len(a) != len("pi05_libero-local-")+12 {
		t.Fatalf("unexpected id: %s", a)
	}
	if a == IDFromPath("/tmp/bundles/other", "pi05_libero") {
		t.Fatal("different path should differ")
	}
}

func TestIDFromRepo(t *testing.T) {
	id := IDFromRepo("https://flashhub-api.example/api/v1/repos/ns/b:1.0.0", "b")
	if !strings.HasPrefix(id, "b-") || strings.Contains(id, "local") {
		t.Fatalf("unexpected id: %s", id)
	}
}

func TestMarkerRoundTrip(t *testing.T) {
	t.Setenv("FLASHCLI_RUNTIMES_DIR", t.TempDir())
	id := "b-local-abc"
	write := WriteMarker(id, map[string]any{"runtime_id": id, "source": "local"})
	if write != nil {
		t.Fatal(write)
	}
	got := ReadMarker(id)
	if got == nil || got["source"] != "local" {
		t.Fatalf("marker = %v", got)
	}
	if _, err := os.Stat(filepath.Join(Dir(id), ".runtime.json")); err != nil {
		t.Fatal(err)
	}
}
