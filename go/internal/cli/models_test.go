package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func cliOutput(t *testing.T, args ...string) string {
	t.Helper()
	cmd := New()
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs(args)
	if err := cmd.Execute(); err != nil {
		t.Fatalf("execute %v: %v\n%s", args, err, buf.String())
	}
	return buf.String()
}

func writePresetMarker(t *testing.T, cacheKey, root, ref string) {
	t.Helper()
	dir := filepath.Join(os.Getenv("FLASHCLI_HOME"), "bundles", filepath.FromSlash(cacheKey))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(map[string]any{
		"ref": ref, "bundle_root": root, "env_key": "sm89-cu124-linux-x86_64-py310",
	})
	if err := os.WriteFile(filepath.Join(dir, ".flashcli_bundle.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
}

func writeCheckpointFiles(t *testing.T, rel ...string) {
	t.Helper()
	for _, name := range rel {
		p := filepath.Join(os.Getenv("FLASHCLI_HOME"), "models", "demo", "1.0.0", "checkpoint", name)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestModelsListStaleBundleRootIsMissing(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	writePresetMarker(t, "demo/1.0.0", filepath.Join(home, "does-not-exist"), "flashcli-bundle/demo:1.0.0")
	out := cliOutput(t, "models", "list")
	if !strings.Contains(out, "missing") {
		t.Fatalf("stale bundle_root must be reported missing, got:\n%s", out)
	}
	if strings.Contains(out, "cached") {
		t.Fatalf("stale bundle_root must not be reported cached, got:\n%s", out)
	}
}

func TestModelsListLegacyWeightsCached(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundleDir := filepath.Join(home, "bundles", "demo", "1.0.0")
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundleDir)
	manifestPath := filepath.Join(bundleDir, "flashcli-bundle.json")
	blob, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	var manifestData map[string]any
	if err := json.Unmarshal(blob, &manifestData); err != nil {
		t.Fatal(err)
	}
	manifestData["weights"] = map[string]any{
		"source": "huggingface", "repo": "org/demo", "revision": "main",
	}
	blob, _ = json.Marshal(manifestData)
	if err := os.WriteFile(manifestPath, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	writePresetMarker(t, "demo/1.0.0", bundleDir, "flashcli-bundle/demo:1.0.0")
	writeCheckpointFiles(t, "config.json", "model.safetensors")

	out := cliOutput(t, "models", "list")
	if !strings.Contains(out, "cached") || !strings.Contains(out, "WEIGHTS") {
		t.Fatalf("legacy ready weights must be reported cached, got:\n%s", out)
	}
	got := cliOutput(t, "models", "show", "flashcli-bundle/demo:1.0.0")
	for _, want := range []string{"source: huggingface", "repo: org/demo", "revision: main", "status: cached"} {
		if !strings.Contains(got, want) {
			t.Fatalf("models show missing %q, got:\n%s", want, got)
		}
	}
}

func TestModelsListIncompleteWeightsIsMissing(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundleDir := filepath.Join(home, "bundles", "demo", "1.0.0")
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundleDir)
	writePresetMarker(t, "demo/1.0.0", bundleDir, "flashcli-bundle/demo:1.0.0")
	writeCheckpointFiles(t, "config.json", "model.safetensors", ".flashcli_download.incomplete")

	out := cliOutput(t, "models", "list")
	if !strings.Contains(out, "missing") {
		t.Fatalf("incomplete weights must be reported missing, got:\n%s", out)
	}
}

func TestModelsListLegacyVariantMarkerCached(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundleDir := filepath.Join(home, "bundles", "demo", "1.0.0")
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundleDir)
	manifestPath := filepath.Join(bundleDir, "flashcli-bundle.json")
	blob, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(blob, &m); err != nil {
		t.Fatal(err)
	}
	m["variants"] = map[string]any{"abi": map[string]any{"weights_dir": "checkpoint"}}
	blob, _ = json.Marshal(m)
	if err := os.WriteFile(manifestPath, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	writePresetMarker(t, "demo/1.0.0", bundleDir, "flashcli-bundle/demo:1.0.0")
	cp := filepath.Join(home, "models", "demo", "1.0.0", "checkpoint")
	if err := os.MkdirAll(cp, 0o755); err != nil {
		t.Fatal(err)
	}
	marker, _ := json.Marshal(map[string]any{"preset": "demo", "checkpoint": cp})
	if err := os.WriteFile(filepath.Join(cp, ".flashcli_model.json"), marker, 0o644); err != nil {
		t.Fatal(err)
	}
	out := cliOutput(t, "models", "list")
	if !strings.Contains(out, "cached") {
		t.Fatalf("legacy variant-less marker must fall back to the model marker, got:\n%s", out)
	}
}

func TestModelsListShowsUsage(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundleDir := filepath.Join(home, "bundles", "demo", "1.0.0")
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundleDir)
	writePresetMarker(t, "demo/1.0.0", bundleDir, "flashcli-bundle/demo:1.0.0")
	dir := filepath.Join(home, "models", "demo", "1.0.0", "checkpoint")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "model.safetensors"), make([]byte, 2048), 0o644); err != nil {
		t.Fatal(err)
	}
	out := cliOutput(t, "models", "list")
	for _, want := range []string{"BUNDLE SIZE", "WEIGHTS SIZE", "2.0 KiB"} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %q in output:\n%s", want, out)
		}
	}
}

func TestDUUsage(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	out := cliOutput(t, "du")
	for _, want := range []string{"Disk usage (apparent size)", "bundles", "models", "runtimes", "total"} {
		if !strings.Contains(out, want) {
			t.Fatalf("missing %q in output:\n%s", want, out)
		}
	}
}
