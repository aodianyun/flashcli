package nativeexec

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

func fixtureRoot(t *testing.T) string {
	t.Helper()
	abs, err := filepath.Abs(filepath.Join("..", "..", "..", "tests", "conformance", "fixtures", "exec_echo"))
	if err != nil {
		t.Fatal(err)
	}
	return abs
}

func TestPlaceholdersResolve(t *testing.T) {
	ph := Placeholders{
		Checkpoint: "/ckpt",
		BundleRoot: "/bundle",
		ModelsDir:  "/models",
		Preset:     "p",
		Variant:    "v",
		Extra:      map[string]string{"mtp": "/models/mtp"},
	}
	got := ph.Resolve("{checkpoint}/x {bundle_root} {models_dir} {preset} {variant} {extra:mtp}")
	want := "/ckpt/x /bundle /models p v /models/mtp"
	if got != want {
		t.Fatalf("Resolve = %q, want %q", got, want)
	}
}

func TestScriptEnvKeys(t *testing.T) {
	ph := Placeholders{Checkpoint: "/c", BundleRoot: "/b", Preset: "p", Variant: "v", Extra: map[string]string{"mtp_fp8": "/m"}}
	env := ph.ScriptEnv()
	joined := ""
	for _, e := range env {
		joined += e + "\n"
	}
	for _, want := range []string{
		"FLASHCLI_CHECKPOINT=/c",
		"FLASHCLI_BUNDLE_ROOT=/b",
		"FLASHCLI_PRESET=p",
		"FLASHCLI_VARIANT=v",
		"FLASHCLI_EXTRA_WEIGHT_MTP_FP8=/m",
	} {
		if !containsLine(joined, want) {
			t.Fatalf("missing %q in:\n%s", want, joined)
		}
	}
}

func TestSpecFromEntry(t *testing.T) {
	entry := &manifest.EntrySpec{
		Kind:   "native-exec",
		Native: map[string]any{"command": []any{"bin/x"}, "transport": "stdio", "ready_timeout_sec": float64(5)},
	}
	spec, err := SpecFromEntry(entry)
	if err != nil {
		t.Fatal(err)
	}
	if spec.Transport != "stdio" || spec.Cwd != "bundle" || spec.ReadyTimeout != 5*time.Second {
		t.Fatalf("unexpected spec: %+v", spec)
	}
	if len(spec.Command) != 1 || spec.Command[0] != "bin/x" {
		t.Fatalf("command = %v", spec.Command)
	}
}

func TestProcessStdioRoundTrip(t *testing.T) {
	root := fixtureRoot(t)
	entry := &manifest.EntrySpec{Kind: "native-exec", Native: map[string]any{"command": []any{"bin/exec_echo"}}}
	spec, err := SpecFromEntry(entry)
	if err != nil {
		t.Fatal(err)
	}
	ph := Placeholders{Checkpoint: "/tmp/ckpt", BundleRoot: root, ModelsDir: "/m", Preset: "exec_echo"}
	p, err := Start(context.Background(), spec, ph, nil)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer p.Close(context.Background())

	if got := p.Ready()["checkpoint"]; got != "/tmp/ckpt" {
		t.Fatalf("ready checkpoint = %v", got)
	}
	out, err := p.Run(context.Background(), map[string]any{"prompt": "hello"})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if out["echo"] != "hello" {
		t.Fatalf("echo = %v", out["echo"])
	}
}

func containsLine(haystack, needle string) bool {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
