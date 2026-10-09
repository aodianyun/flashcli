package paths

import (
	"path/filepath"
	"testing"
)

func TestHomeModelsBundlesRuntimesCache(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", "/tmp/fc-home")
	t.Setenv("FLASHCLI_MODELS_DIR", "")
	t.Setenv("FLASHCLI_BUNDLES_DIR", "")
	t.Setenv("FLASHCLI_RUNTIMES_DIR", "")

	if got := Home(); got != "/tmp/fc-home" {
		t.Fatalf("Home = %q", got)
	}
	if got := Models(); got != filepath.Join("/tmp/fc-home", "models") {
		t.Fatalf("Models = %q", got)
	}
	if got := Bundles(); got != filepath.Join("/tmp/fc-home", "bundles") {
		t.Fatalf("Bundles = %q", got)
	}
	if got := Runtimes(); got != filepath.Join("/tmp/fc-home", "runtimes") {
		t.Fatalf("Runtimes = %q", got)
	}
	if got := Cache(); got != filepath.Join("/tmp/fc-home", "cache", "downloads") {
		t.Fatalf("Cache = %q", got)
	}

	t.Setenv("FLASHCLI_MODELS_DIR", "/m")
	t.Setenv("FLASHCLI_BUNDLES_DIR", "/b")
	t.Setenv("FLASHCLI_RUNTIMES_DIR", "/r")
	if Models() != "/m" || Bundles() != "/b" || Runtimes() != "/r" {
		t.Fatalf("env overrides ignored: %q %q %q", Models(), Bundles(), Runtimes())
	}
}
