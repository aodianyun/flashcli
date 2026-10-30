package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

func writeBundle(t *testing.T, root string) {
	t.Helper()
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": 3, "protocol_version": 1,
		"name": "demo", "python_abi": "310",
		"entry":   map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{"sm89-cu124-linux-x86_64-py310": "runtime/x"},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, "flashcli-bundle.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "run.py"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestBundleCleanRemovesRuntimes(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	runtimes := filepath.Join(home, "runtimes")
	if err := os.MkdirAll(filepath.Join(runtimes, "x-local-abc"), 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	if _, err := os.Stat(filepath.Join(runtimes, "x-local-abc")); err == nil {
		t.Fatal("runtime dir should be removed")
	}
}

func TestModelsShowLocal(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle := filepath.Join(home, "demo")
	if err := os.MkdirAll(bundle, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, bundle)
	if code := Main([]string{"models", "show", bundle}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
}

func writeRuntimeMarker(t *testing.T, id, preset string) string {
	t.Helper()
	dir := filepath.Join(paths.Runtimes(), id)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(map[string]any{"preset": preset, "runtime_id": id})
	if err := os.WriteFile(filepath.Join(dir, ".runtime.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func mustStat(t *testing.T, path string, wantExist bool) {
	t.Helper()
	_, err := os.Stat(path)
	if (err == nil) != wantExist {
		t.Fatalf("stat %s: exists=%v want %v", path, err == nil, wantExist)
	}
}

func TestBundleCleanAll(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if err := os.MkdirAll(paths.Runtimes(), 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, paths.Runtimes(), false)
}

func TestBundleCleanByRef(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	keep := writeRuntimeMarker(t, "other-local-1", "other")
	drop := writeRuntimeMarker(t, "pi05-local-1", "pi05_libero")
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/pi05_libero:1.0.0", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, drop, false)
	mustStat(t, keep, true)
}

func TestBundleCleanByRefNoMatch(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/none:1.0.0", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
}

func TestBundleCleanAllData(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	for _, d := range []string{paths.Runtimes(), paths.Models(), paths.Bundles()} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	repoIndex := filepath.Join(paths.Cache(), "repo-index")
	if err := os.MkdirAll(repoIndex, 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, paths.Runtimes(), false)
	mustStat(t, paths.Models(), false)
	mustStat(t, paths.Bundles(), false)
	mustStat(t, repoIndex, true) // bundle clean no longer touches FlashHub cache

	if code := Main([]string{"cache", "clean", "--flashhub", "--yes"}); code != 0 {
		t.Fatalf("cache clean exit = %d", code)
	}
	mustStat(t, repoIndex, false)
}

func TestBundleCleanByRefPresetMarkerFallback(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	drop := filepath.Join(paths.Runtimes(), "pi05-1")
	if err := os.MkdirAll(drop, 0o755); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(paths.Bundles(), "pi05_libero", "1.0.0")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, runtime.PresetMarkerName), []byte(`{"runtime_id":"pi05-1"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/pi05_libero:1.0.0", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, drop, false)
}

func TestBundleCleanRefAll(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	rootA := filepath.Join(paths.Bundles(), "a", "1.0.0")
	rootB := filepath.Join(paths.Bundles(), "b", "1.0.0")
	for _, root := range []string{rootA, rootB} {
		if err := os.MkdirAll(root, 0o755); err != nil {
			t.Fatal(err)
		}
		writeBundle(t, root)
	}
	writePresetMarker(t, "a/1.0.0", rootA, "flashcli-bundle/a:1.0.0")
	writePresetMarker(t, "b/1.0.0", rootB, "flashcli-bundle/b:1.0.0")
	modelA := filepath.Join(paths.Models(), "a", "1.0.0", "checkpoint")
	modelB := filepath.Join(paths.Models(), "b", "1.0.0", "checkpoint")
	for _, d := range []string{modelA, modelB} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	rtA := writeRuntimeMarkerWithRoot(t, "a-1", "a", rootA)
	rtB := writeRuntimeMarkerWithRoot(t, "b-1", "b", rootB)

	if code := Main([]string{"bundle", "clean", "flashcli-bundle/a:1.0.0", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, rootA, false)
	mustStat(t, modelA, false)
	mustStat(t, rtA, false)
	mustStat(t, rootB, true)
	mustStat(t, modelB, true)
	mustStat(t, rtB, true)
}

func TestBundleCleanConfirmation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	run := filepath.Join(paths.Runtimes(), "x-1")
	if err := os.MkdirAll(run, 0o755); err != nil {
		t.Fatal(err)
	}
	cmd := New()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	cmd.SetIn(strings.NewReader("n\n"))
	cmd.SetArgs([]string{"bundle", "clean"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("abort execute: %v", err)
	}
	if _, err := os.Stat(run); err != nil {
		t.Fatal("declining confirmation must keep runtime")
	}
	if !strings.Contains(out.String(), "Continue? [y/N]") {
		t.Fatalf("missing prompt:\n%s", out.String())
	}
	out.Reset()
	cmd = New()
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	cmd.SetIn(strings.NewReader("y\n"))
	cmd.SetArgs([]string{"bundle", "clean"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("confirm execute: %v", err)
	}
	mustStat(t, run, false)
}

func TestCacheCleanRejectsBundleRef(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"cache", "clean", "flashcli-bundle/pi05_libero:1.0.0", "--all"}); code == 0 {
		t.Fatal("cache clean must reject a bundle ref and point at bundle clean")
	}
}

func writeRuntimeMarkerWithRoot(t *testing.T, id, preset, root string) string {
	t.Helper()
	dir := filepath.Join(paths.Runtimes(), id)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(map[string]any{
		"preset": preset, "runtime_id": id, "bundle_root": root,
	})
	if err := os.WriteFile(filepath.Join(dir, ".runtime.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestBundleCleanOrphans(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	validRoot := filepath.Join(paths.Bundles(), "demo", "1.0.0")
	if err := os.MkdirAll(validRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	writeBundle(t, validRoot)
	writePresetMarker(t, "demo/1.0.0", validRoot, "flashcli-bundle/demo:1.0.0")
	keepRuntime := writeRuntimeMarkerWithRoot(t, "demo-1", "demo", validRoot)

	staleRoot := filepath.Join(home, "gone")
	writePresetMarker(t, "stale/1.0.0", staleRoot, "flashcli-bundle/stale:1.0.0")
	staleBundle := filepath.Join(paths.Bundles(), "stale", "1.0.0")
	staleModel := filepath.Join(paths.Models(), "stale", "1.0.0", "checkpoint")
	if err := os.MkdirAll(staleModel, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(staleModel, "model.safetensors"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	staleRuntime := writeRuntimeMarkerWithRoot(t, "stale-1", "stale", staleRoot)
	noMarkerRuntime := filepath.Join(paths.Runtimes(), "no-marker")
	if err := os.MkdirAll(noMarkerRuntime, 0o755); err != nil {
		t.Fatal(err)
	}

	if code := Main([]string{"bundle", "clean", "--orphans", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, validRoot, true)
	mustStat(t, keepRuntime, true)
	mustStat(t, staleBundle, false)
	mustStat(t, staleModel, false)
	mustStat(t, staleRuntime, false)
	mustStat(t, noMarkerRuntime, false)
}

func TestBundleCleanOrphansRejectsCombinations(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	for _, args := range [][]string{
		{"bundle", "clean", "--orphans", "--all"},
		{"bundle", "clean", "--orphans", "flashcli-bundle/demo:1.0.0"},
	} {
		if code := Main(args); code == 0 {
			t.Fatalf("%v must fail", args)
		}
	}
}

func TestBundleCleanAmbiguousLocalRefAll(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	var bundles, models, runtimes []string
	for _, suffix := range []string{"a", "b"} {
		key := "echo-local-" + suffix + "/local"
		bundleDir := filepath.Join(paths.Bundles(), filepath.FromSlash(key))
		if err := os.MkdirAll(bundleDir, 0o755); err != nil {
			t.Fatal(err)
		}
		writeBundle(t, bundleDir)
		rt := writeRuntimeMarkerWithRoot(t, "echo-local-"+suffix, "echo", bundleDir)
		writePresetMarker(t, key, bundleDir, "echo")
		// Add runtime_id so the stale/no-runtime fallback is not needed.
		markerPath := filepath.Join(bundleDir, runtime.PresetMarkerName)
		blob, _ := os.ReadFile(markerPath)
		var m map[string]any
		_ = json.Unmarshal(blob, &m)
		m["runtime_id"] = "echo-local-" + suffix
		blob, _ = json.Marshal(m)
		if err := os.WriteFile(markerPath, blob, 0o644); err != nil {
			t.Fatal(err)
		}
		modelDir := filepath.Join(paths.Models(), filepath.FromSlash(key))
		if err := os.MkdirAll(modelDir, 0o755); err != nil {
			t.Fatal(err)
		}
		bundles = append(bundles, bundleDir)
		models = append(models, modelDir)
		runtimes = append(runtimes, rt)
	}

	if code := Main([]string{"bundle", "clean", "echo", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	for _, p := range append(append(bundles, models...), runtimes...) {
		if _, err := os.Stat(p); err == nil {
			t.Fatalf("expected %s removed", p)
		}
	}
}

func TestBundleCleanV4UsesStoreKey(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundleDir := filepath.Join(paths.Bundles(), "demo", "1.0.0")
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeV4ExecBundle(t, bundleDir)
	writePresetMarker(t, "demo/1.0.0", bundleDir, "flashcli-bundle/demo:1.0.0")
	man, err := manifest.Load(bundleDir)
	if err != nil {
		t.Fatal(err)
	}
	storeDir := filepath.Join(paths.Models(), filepath.FromSlash(weights.StoreKeyFor(man, "")))
	if err := os.MkdirAll(storeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(storeDir, "model.safetensors"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/demo:1.0.0", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	mustStat(t, bundleDir, false)
	mustStat(t, storeDir, false)
}

func TestBundleCleanV4SharedWeightsKept(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	a := filepath.Join(paths.Bundles(), "a", "1.0.0")
	b := filepath.Join(paths.Bundles(), "b", "1.0.0")
	for _, root := range []string{a, b} {
		if err := os.MkdirAll(root, 0o755); err != nil {
			t.Fatal(err)
		}
		writeV4ExecBundle(t, root)
	}
	writePresetMarker(t, "a/1.0.0", a, "flashcli-bundle/a:1.0.0")
	writePresetMarker(t, "b/1.0.0", b, "flashcli-bundle/b:1.0.0")
	man, err := manifest.Load(a)
	if err != nil {
		t.Fatal(err)
	}
	storeDir := filepath.Join(paths.Models(), filepath.FromSlash(weights.StoreKeyFor(man, "")))
	if err := os.MkdirAll(storeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/a:1.0.0", "--all", "--yes"}); code != 0 {
		t.Fatalf("first clean exit = %d", code)
	}
	mustStat(t, a, false)
	mustStat(t, storeDir, true)
	if code := Main([]string{"bundle", "clean", "flashcli-bundle/b:1.0.0", "--all", "--yes"}); code != 0 {
		t.Fatalf("second clean exit = %d", code)
	}
	mustStat(t, storeDir, false)
}
