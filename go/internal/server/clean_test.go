package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

func TestCleanModels(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	key := "demo/1"
	bundleDir := filepath.Join(paths.Bundles(), filepath.FromSlash(key))
	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatal(err)
	}
	marker, _ := json.Marshal(map[string]any{
		"ref": "demo:1", "cache_key": key, "bundle_root": bundleDir, "weights_key": "demo/1",
	})
	if err := os.WriteFile(filepath.Join(bundleDir, flashhub.MarkerName), marker, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(bundleDir, "payload"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}
	weightsDir := filepath.Join(paths.Models(), "demo", "1")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}

	s := &Server{}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/models/clean",
		strings.NewReader(`{"refs":["demo:1","missing"]}`))
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var payload struct {
		Results []cleanResult `json:"results"`
		Freed   int64         `json:"freed_bytes"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Results) != 2 {
		t.Fatalf("results=%+v", payload.Results)
	}
	if !payload.Results[0].Removed || payload.Freed <= 0 {
		t.Fatalf("first result=%+v freed=%d", payload.Results[0], payload.Freed)
	}
	if payload.Results[1].Skipped == "" {
		t.Fatalf("missing ref should be skipped: %+v", payload.Results[1])
	}
	if _, err := os.Stat(bundleDir); !os.IsNotExist(err) {
		t.Fatalf("bundle dir still exists: %v", err)
	}
}

func TestCleanModelsValidation(t *testing.T) {
	s := &Server{}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/models/clean", strings.NewReader(`{}`))
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status=%d", rec.Code)
	}
}

func TestCleanStorage(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	cache := filepath.Join(home, "cache", "uv", "file.bin")
	if err := os.MkdirAll(filepath.Dir(cache), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cache, make([]byte, 8192), 0o644); err != nil {
		t.Fatal(err)
	}
	s := &Server{}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/storage/clean",
		strings.NewReader(`{"targets":["cache"]}`))
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var payload struct {
		Freed int64 `json:"freed_bytes"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Freed <= 0 {
		t.Fatalf("freed=%d", payload.Freed)
	}
	if _, err := os.Stat(filepath.Join(home, "cache")); !os.IsNotExist(err) {
		t.Fatalf("cache still exists: %v", err)
	}
}

func TestCleanModelsKeepsSharedRuntimeAndWeights(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	keys := []string{"a/1.0.0", "b/1.0.0"}
	refs := []string{"a:1.0.0", "b:1.0.0"}
	roots := make([]string, len(keys))
	for i, key := range keys {
		roots[i] = filepath.Join(paths.Bundles(), filepath.FromSlash(key))
		if err := os.MkdirAll(roots[i], 0o755); err != nil {
			t.Fatal(err)
		}
		marker, _ := json.Marshal(map[string]any{
			"ref": refs[i], "cache_key": key, "bundle_root": roots[i],
			"weights_key": "shared/weights", "runtime_id": "shared-runtime",
		})
		if err := os.WriteFile(filepath.Join(roots[i], flashhub.MarkerName), marker, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	weightsDir := filepath.Join(paths.Models(), "shared", "weights")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := runtime.WriteMarker("shared-runtime", map[string]any{"runtime_id": "shared-runtime", "bundle_root": roots[0]}); err != nil {
		t.Fatal(err)
	}
	runtimeDir := runtime.Dir("shared-runtime")
	if err := os.WriteFile(filepath.Join(runtimeDir, "torch.bin"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}

	s := &Server{}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/v1/models/clean",
		strings.NewReader(`{"refs":["a:1.0.0"]}`))
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var payload struct {
		Results []cleanResult `json:"results"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Results) != 1 || !payload.Results[0].SharedWeights {
		t.Fatalf("results=%+v", payload.Results)
	}
	if _, err := os.Stat(roots[0]); !os.IsNotExist(err) {
		t.Fatalf("target bundle still exists: %v", err)
	}
	if _, err := os.Stat(roots[1]); err != nil {
		t.Fatalf("other bundle removed: %v", err)
	}
	if _, err := os.Stat(weightsDir); err != nil {
		t.Fatalf("shared weights removed: %v", err)
	}
	if _, err := os.Stat(runtimeDir); err != nil {
		t.Fatalf("shared runtime removed: %v", err)
	}
}

func TestCleanStorageRejectsModelTargets(t *testing.T) {
	s := &Server{}
	for _, target := range []string{"runtimes", "all"} {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/v1/storage/clean",
			strings.NewReader(`{"targets":["`+target+`"]}`))
		s.Handler().ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("%s: status=%d body=%s", target, rec.Code, rec.Body.String())
		}
	}
}
