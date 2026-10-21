package venv

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/progress"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

func testManifest(t *testing.T) *manifest.Manifest {
	t.Helper()
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"name": "t", "python_abi": "310",
		"entry":   map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{"sm89-cu124-linux-x86_64-py310": "runtime/x"},
		"python_dependencies": map[string]any{
			"torch": map[string]any{"package": "torch", "index": "cu124"},
			"pip":   []any{"numpy", "safetensors"},
		},
	}
	m, err := manifest.LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	return m
}

type failRunner struct{ t *testing.T }

func (f failRunner) Run(context.Context, []string, []string) error {
	f.t.Fatal("runner should not be called")
	return nil
}

func TestFingerprintStableAndSensitive(t *testing.T) {
	m := testManifest(t)
	a := Fingerprint(m, "cu124")
	if a != Fingerprint(m, "cu124") {
		t.Fatal("fingerprint not stable")
	}
	if a == Fingerprint(m, "cu128") {
		t.Fatal("fingerprint should change with torch index")
	}
}

func TestParseTorchDependency(t *testing.T) {
	if pkg, idx := ParseTorchDependency(map[string]any{"package": "torch", "index": "auto"}); pkg != "torch" || idx != "auto" {
		t.Fatalf("dict -> %q %q", pkg, idx)
	}
	if pkg, _ := ParseTorchDependency(false); pkg != "" {
		t.Fatalf("false -> %q", pkg)
	}
	if pkg, _ := ParseTorchDependency("skip"); pkg != "" {
		t.Fatalf("skip -> %q", pkg)
	}
	if pkg, _ := ParseTorchDependency("torch>=2"); pkg != "torch>=2" {
		t.Fatalf("string -> %q", pkg)
	}
}

func TestInstallPlan(t *testing.T) {
	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	m := testManifest(t)
	plan := InstallPlan("/v/bin/python", m, "cu124", true)
	if len(plan) != 3 {
		t.Fatalf("plan len = %d: %v", len(plan), plan)
	}
	joined := make([]string, len(plan))
	for i, argv := range plan {
		joined[i] = strings.Join(argv, " ")
	}
	if !strings.Contains(joined[0], "flashcli-bundle[infer]") {
		t.Fatalf("first install should be infer: %s", joined[0])
	}
	if !strings.Contains(joined[1], "download.pytorch.org/whl/cu124") || !strings.Contains(joined[1], "torch") {
		t.Fatalf("torch install wrong: %s", joined[1])
	}
	if !strings.Contains(joined[2], "numpy") || !strings.Contains(joined[2], "safetensors") {
		t.Fatalf("pip deps wrong: %s", joined[2])
	}
}

func TestEnsureReusesMatchingVenv(t *testing.T) {
	t.Setenv("FLASHCLI_RUNTIMES_DIR", t.TempDir())
	m := testManifest(t)
	id := "t-local-abc"
	venvDir := runtime.VenvDir(id)
	python := filepath.Join(venvDir, "bin", "python")
	if err := os.MkdirAll(filepath.Dir(python), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(python, []byte("#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then echo 3.10; exit 0; fi\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	fp := Fingerprint(m, "cu124")
	if err := os.MkdirAll(runtime.Dir(id), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(runtime.FingerprintPath(id), []byte(fp+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := Ensure(context.Background(), id, m, Options{Runner: failRunner{t}, Quiet: true})
	if err != nil {
		t.Fatal(err)
	}
	if got != python {
		t.Fatalf("python = %q, want %q", got, python)
	}
}

func TestEnsureReportsInstallOrigin(t *testing.T) {
	t.Setenv("FLASHCLI_RUNTIMES_DIR", t.TempDir())
	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "")
	var buf bytes.Buffer
	progress.SetOutput(&buf)
	progress.SetQuiet(false)
	t.Cleanup(func() {
		progress.SetOutput(os.Stderr)
		progress.SetQuiet(false)
	})

	m := testManifest(t)
	_, _ = Ensure(context.Background(), "t-report-1", m, Options{BasePython: "/bin/false", Runner: okRunner{}})

	got := buf.String()
	if !strings.Contains(got, "flashcli-bundle[infer] from") {
		t.Fatalf("missing install-origin note: %q", got)
	}
	if !strings.Contains(got, "from ") || !strings.Contains(got, "torch") {
		t.Fatalf("missing torch source note: %q", got)
	}
}

type okRunner struct{}

func (okRunner) Run(context.Context, []string, []string) error { return nil }

func TestEnsureSkipSetup(t *testing.T) {
	t.Setenv("FLASHCLI_RUNTIMES_DIR", t.TempDir())
	m := testManifest(t)
	id := "t-local-xyz"
	if _, err := Ensure(context.Background(), id, m, Options{SkipSetup: true}); err == nil {
		t.Fatal("expected error when venv python missing")
	}
}

func TestResolveBasePythonChecksABI(t *testing.T) {
	dir := t.TempDir()
	write := func(name, ver string) string {
		t.Helper()
		p := filepath.Join(dir, name)
		script := "#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then echo '" + ver + "'; exit 0; fi\nexit 1\n"
		if err := os.WriteFile(p, []byte(script), 0o755); err != nil {
			t.Fatal(err)
		}
		return p
	}
	write("python3", "3.12")
	t.Setenv("PATH", dir)
	t.Setenv("FLASHCLI_PYTHON_ROOT", filepath.Join(dir, "pyroot"))
	t.Setenv("FLASHCLI_PYTHON_ENV", filepath.Join(dir, "noenv"))
	t.Setenv("FLASHCLI_PY310_BIN", "")
	t.Setenv("FLASHCLI_BASE_PYTHON", "")

	if got, err := ResolveBasePython("310"); err == nil {
		t.Fatalf("expected error for python3=3.12 with abi=310, got %q", got)
	}

	py310 := write("python3.10", "3.10")
	if got, err := ResolveBasePython("310"); err != nil || got != py310 {
		t.Fatalf("ResolveBasePython(310) = %q, %v; want %q", got, err, py310)
	}
}
