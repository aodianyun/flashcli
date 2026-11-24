package manifest

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func staticTestManifest(t *testing.T, body string, caps []string, set bool) (*Manifest, string) {
	t.Helper()
	dir := t.TempDir()
	file := filepath.Join(dir, "serve.py")
	if err := os.WriteFile(file, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	spec := &EntrySpec{
		Kind: "python", Mode: "engine", Module: "serve", Attr: "ServeEngine",
		Capabilities: caps, CapabilitiesSet: set,
	}
	return &Manifest{Root: dir, EntryServe: spec}, file
}

const staticBase = `class ServeEngine:
    model_id = "m"
    def load(self, checkpoint, preset, **options): pass
    def warmup(self, spec=None): pass
`

func TestValidateServeMethodsMissing(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, staticBase, []string{"openai.embeddings"}, true)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "embed") {
		t.Fatalf("errors = %v", errs)
	}

	m, _ = staticTestManifest(
		t,
		staticBase+"    def embed(self, request): pass\n",
		[]string{"openai.embeddings"},
		true,
	)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("complete engine errors = %v", errs)
	}
}

func TestValidateServeMethodsSkipsInheritedAndImported(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	inherited := "class Base: pass\n" + strings.ReplaceAll(staticBase, "class ServeEngine:", "class ServeEngine(Base):")
	m, _ := staticTestManifest(t, inherited, []string{"openai.embeddings"}, true)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("inherited class errors = %v", errs)
	}

	m, _ = staticTestManifest(
		t,
		"from somewhere import ServeEngine\n",
		[]string{"openai.embeddings"},
		true,
	)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("imported class errors = %v", errs)
	}
}

func TestValidateServeMethodsExplicitEmptyAndLegacy(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, staticBase, []string{}, true)
	if errs := ValidateServeMethods(m); len(errs) != 0 {
		t.Fatalf("empty capabilities errors = %v", errs)
	}

	m, _ = staticTestManifest(t, staticBase, nil, false)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "chat") {
		t.Fatalf("legacy capabilities errors = %v", errs)
	}
}

func TestValidateServeMethodsSyntaxError(t *testing.T) {
	if _, _, ok := staticPython(); !ok {
		t.Skip("python interpreter not available")
	}
	m, _ := staticTestManifest(t, "class ServeEngine(:\n", []string{}, true)
	errs := ValidateServeMethods(m)
	if len(errs) != 1 || !strings.Contains(errs[0], "line") {
		t.Fatalf("syntax errors = %v", errs)
	}
}
