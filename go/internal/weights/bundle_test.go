package weights

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

func loadManifest(t *testing.T, data map[string]any) *manifest.Manifest {
	t.Helper()
	m, err := manifest.LoadData(data, "/tmp/bundle")
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func baseBundleData() map[string]any {
	return map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"name": "demo", "python_abi": "310",
		"entry":   map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{"sm120-cu130-linux-x86_64-py310": "runtime/x"},
	}
}

func TestEnvMapExpandsPlaceholders(t *testing.T) {
	t.Setenv("FLASHCLI_MODELS_DIR", "/models")
	data := baseBundleData()
	data["env"] = map[string]any{"FOO": "{models_dir}/x", "BAR": "{bundle_root}/y"}
	m := loadManifest(t, data)
	env := EnvMap(m, "")
	if env["FOO"] != "/models/x" {
		t.Fatalf("FOO = %q", env["FOO"])
	}
	if env["BAR"] != "/tmp/bundle/y" {
		t.Fatalf("BAR = %q", env["BAR"])
	}
}

func TestPrepareBundleVersionCacheKey(t *testing.T) {
	models := t.TempDir()
	t.Setenv("FLASHCLI_MODELS_DIR", models)
	m := loadManifest(t, baseBundleData())
	checkpoint, _, err := PrepareBundle(context.Background(), m, "1.2.3", "", true)
	if err != nil {
		t.Fatalf("PrepareBundle: %v", err)
	}
	if !strings.Contains(filepath.ToSlash(checkpoint), "/demo/1.2.3/checkpoint") {
		t.Fatalf("checkpoint = %q, want version in cache key", checkpoint)
	}
}

func TestPrepareBundleExtraPull(t *testing.T) {
	content := "{}"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/models/o/r/tree/main":
			_ = json.NewEncoder(w).Encode([]map[string]any{{"type": "file", "path": "config.json", "size": len(content)}})
		case r.URL.Path == "/o/r/resolve/main/config.json":
			_, _ = w.Write([]byte(content))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	models := t.TempDir()
	t.Setenv("FLASHCLI_MODELS_DIR", models)
	data := baseBundleData()
	data["extra_pull"] = map[string]any{
		"extra": map[string]any{
			"source": "huggingface", "repo": "o/r", "endpoint": srv.URL,
			"allow_patterns": []any{"config.json"}, "cache_name": "extra_cache",
		},
	}
	m := loadManifest(t, data)
	if _, _, err := PrepareBundle(context.Background(), m, "local", "", true); err != nil {
		t.Fatalf("PrepareBundle: %v", err)
	}
	if _, err := os.Stat(filepath.Join(models, "extra_cache", "config.json")); err != nil {
		t.Fatalf("extra_pull file missing: %v", err)
	}
}
