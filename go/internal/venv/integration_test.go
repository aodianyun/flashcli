package venv

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// Opt-in: FLASHCLI_UV_TEST=1 (needs uv + the PyPI mirror). Creates a minimal
// venv (flashcli-bundle[infer] only) with the uv backend and checks reuse.
func TestUVVenvIntegration(t *testing.T) {
	if os.Getenv("FLASHCLI_UV_TEST") != "1" {
		t.Skip("set FLASHCLI_UV_TEST=1 to create a uv venv")
	}
	base := ""
	for _, name := range []string{"python3.12", "python3"} {
		if p, err := exec.LookPath(name); err == nil {
			base = p
			break
		}
	}
	if base == "" {
		t.Skip("no python3")
	}
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not on PATH")
	}
	specDir := "/app/flashcli/flashcli-bundle"
	if _, err := os.Stat(specDir); err != nil {
		t.Skip("no local flashcli-bundle checkout")
	}
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("FLASHCLI_VENV_BACKEND", "uv")
	t.Setenv("PIP_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")
	t.Setenv("PIP_TRUSTED_HOST", "mirrors.aliyun.com")
	t.Setenv("UV_CACHE_DIR", filepath.Join(home, "cache", "uv"))
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", specDir+"[infer]")

	m := &manifest.Manifest{Name: "uvtest", Root: t.TempDir(), Raw: map[string]any{
		"python_abi":          "312",
		"python_dependencies": map[string]any{"pip": []any{}},
	}}
	ctx := context.Background()
	py, err := Ensure(ctx, "uvtest-local", m, Options{Quiet: true, NoAutoInstall: true, BasePython: base})
	if err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command(py, "-c", "import flashcli_bundle;print('ok')").CombinedOutput()
	if err != nil {
		t.Fatalf("import flashcli_bundle failed: %s (%v)", out, err)
	}
	py2, err := Ensure(ctx, "uvtest-local", m, Options{Quiet: true, NoAutoInstall: true, BasePython: base})
	if err != nil {
		t.Fatal(err)
	}
	if py2 != py {
		t.Fatalf("second Ensure rebuilt the venv: %q != %q", py2, py)
	}
}
