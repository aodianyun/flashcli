package venv

import (
	"context"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

type captureRunner struct {
	calls [][]string
}

func (c *captureRunner) Run(_ context.Context, argv []string, _ []string) error {
	c.calls = append(c.calls, argv)
	return nil
}

// stubPython writes an executable that ignores its args and prints out.
func stubPython(t *testing.T, out string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "python")
	script := "#!/bin/sh\nprintf '%s\\n' " + out + "\n"
	if err := os.WriteFile(p, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestProbeCacheSchema(t *testing.T) {
	if n, ok := probeCacheSchema(context.Background(), stubPython(t, "2")); !ok || n != 2 {
		t.Fatalf("got (%d,%v) want (2,true)", n, ok)
	}
	if n, ok := probeCacheSchema(context.Background(), stubPython(t, "bogus")); ok || n != 0 {
		t.Fatalf("got (%d,%v) want (0,false)", n, ok)
	}
	if _, ok := probeCacheSchema(context.Background(), filepath.Join(t.TempDir(), "missing")); ok {
		t.Fatal("missing python should not probe ok")
	}
}

func TestEnsureProtocolCacheSchemaSkipsCurrent(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "flashcli-bundle[infer]")
	r := &captureRunner{}
	err := EnsureProtocolCacheSchema(context.Background(), stubPython(t, strconv.Itoa(RequiredCacheSchema)), Options{Runner: r, Quiet: true})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.calls) != 0 {
		t.Fatalf("current schema must not upgrade: %v", r.calls)
	}
}

func TestEnsureProtocolCacheSchemaUpgradesStale(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "flashcli-bundle[infer]")
	t.Setenv("FLASHCLI_VENV_BACKEND", "pip")
	r := &captureRunner{}
	err := EnsureProtocolCacheSchema(context.Background(), stubPython(t, "0"), Options{Runner: r, Quiet: true})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.calls) != 1 {
		t.Fatalf("stale schema must upgrade once: %v", r.calls)
	}
	joined := strings.Join(r.calls[0], " ")
	for _, want := range []string{"-m pip install", "--force-reinstall", "--no-deps", "flashcli-bundle[infer]"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("upgrade argv missing %q: %s", want, joined)
		}
	}
}

// stubUV is an executable that reports a version for --version.
func stubUV(t *testing.T, version string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "uv")
	script := "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo \"uv " + version + "\"; exit 0; fi\nexit 0\n"
	if err := os.WriteFile(p, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestEnsureProtocolCacheSchemaUpgradesViaUV(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "flashcli-bundle[infer]")
	t.Setenv("FLASHCLI_VENV_BACKEND", "uv")
	uvBin := stubUV(t, "0.9.3")
	t.Setenv("FLASHCLI_UV_BIN", uvBin)
	r := &captureRunner{}
	py := stubPython(t, "0")
	if err := EnsureProtocolCacheSchema(context.Background(), py, Options{Runner: r, Quiet: true}); err != nil {
		t.Fatal(err)
	}
	if len(r.calls) != 1 {
		t.Fatalf("stale schema must upgrade once: %v", r.calls)
	}
	got := r.calls[0]
	if len(got) < 4 || got[0] != uvBin || got[1] != "pip" || got[2] != "install" || got[3] != "--python" {
		t.Fatalf("unexpected uv argv: %v", got)
	}
	joined := strings.Join(got, " ")
	for _, want := range []string{"--python " + py, "--force-reinstall", "--no-deps", "flashcli-bundle[infer]"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("uv argv missing %q: %s", want, joined)
		}
	}
}
