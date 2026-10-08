package weights

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestCacheKey(t *testing.T) {
	if got := CacheKey("qwen_nvfp4", "1.0.1", "qwen36"); got != "qwen_nvfp4/1.0.1@qwen36" {
		t.Fatalf("CacheKey = %q", got)
	}
	if got := CacheKey("pi05", "1.0.4", ""); got != "pi05/1.0.4" {
		t.Fatalf("CacheKey = %q", got)
	}
}

func TestMarkerRoundTrip(t *testing.T) {
	dir := t.TempDir()
	if err := WriteMarker(dir, "pi05", "/models/pi05/checkpoint"); err != nil {
		t.Fatal(err)
	}
	got, ok := ReadMarker(dir)
	if !ok || got != "/models/pi05/checkpoint" {
		t.Fatalf("ReadMarker = %q, %v", got, ok)
	}
}

func TestHasUsableCheckpoint(t *testing.T) {
	dir := t.TempDir()
	if HasUsableCheckpoint(dir, false) {
		t.Fatal("empty dir should not be usable")
	}
	writeFile(t, filepath.Join(dir, "config.json"), "{}")
	writeFile(t, filepath.Join(dir, "model.safetensors"), "w")
	if !HasUsableCheckpoint(dir, false) {
		t.Fatal("config + main safetensors should be usable")
	}
	if HasUsableCheckpoint(dir, true) {
		t.Fatal("norm stats required but absent")
	}
	writeFile(t, filepath.Join(dir, "norm_stats.json"), "{}")
	if !HasUsableCheckpoint(dir, true) {
		t.Fatal("norm stats present should be usable")
	}
}

func TestMatchPatternDoubleStar(t *testing.T) {
	if !matchPattern("a/b/c.txt", "**/*.txt") {
		t.Fatal("** should match nested")
	}
	if !matchPattern("c.txt", "**/*.txt") {
		t.Fatal("**/ should match zero dirs")
	}
	if matchPattern("a/b/c.bin", "**/*.txt") {
		t.Fatal("extension mismatch")
	}
}

func TestDownloadHuggingFace(t *testing.T) {
	contents := map[string]string{
		"config.json":       "{}",
		"model.safetensors": "weightsdata",
		"readme.md":         "skip me",
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/models/o/r/tree/main":
			_ = json.NewEncoder(w).Encode([]map[string]any{
				{"type": "file", "path": "config.json", "size": len(contents["config.json"])},
				{"type": "file", "path": "model.safetensors", "size": len(contents["model.safetensors"])},
				{"type": "file", "path": "readme.md", "size": len(contents["readme.md"])},
			})
		case strings.HasPrefix(r.URL.Path, "/o/r/resolve/main/"):
			name := strings.TrimPrefix(r.URL.Path, "/o/r/resolve/main/")
			body, ok := contents[name]
			if !ok {
				http.NotFound(w, r)
				return
			}
			serveRange(w, r, body)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dest := t.TempDir()
	spec := Spec{Source: "huggingface", Repo: "o/r", Endpoint: srv.URL, Raw: map[string]any{}}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(dest, "model.safetensors")); string(b) != "weightsdata" {
		t.Fatalf("weights content = %q", b)
	}
	if _, err := os.Stat(filepath.Join(dest, "readme.md")); err != nil {
		t.Fatal("readme.md should be downloaded too (no allow_patterns)")
	}
}

func TestDownloadHuggingFaceResumes(t *testing.T) {
	body := "weightsdata"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/models/o/r/tree/main":
			_ = json.NewEncoder(w).Encode([]map[string]any{
				{"type": "file", "path": "model.safetensors", "size": len(body)},
			})
		case r.URL.Path == "/o/r/resolve/main/model.safetensors":
			serveRange(w, r, body)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dest := t.TempDir()
	writeFile(t, filepath.Join(dest, "model.safetensors.incomplete"), "wei")
	spec := Spec{Source: "huggingface", Repo: "o/r", Endpoint: srv.URL, Raw: map[string]any{}}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if got, _ := os.ReadFile(filepath.Join(dest, "model.safetensors")); string(got) != body {
		t.Fatalf("resumed content = %q, want %q", got, body)
	}
}

func TestDownloadModelScope(t *testing.T) {
	contents := map[string]string{
		"config.json":       "{}",
		"model.safetensors": "msdata",
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/models/o/r/repo/files":
			if r.URL.Query().Get("PageNumber") != "1" {
				_ = json.NewEncoder(w).Encode(map[string]any{"Code": 200, "Data": map[string]any{"Files": []any{}}})
				return
			}
			files := []map[string]any{}
			for p, c := range contents {
				files = append(files, map[string]any{"Path": p, "Type": "blob", "Size": len(c)})
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"Code": 200, "Data": map[string]any{"Files": files}})
		case "/api/v1/models/o/r/repo":
			body, ok := contents[r.URL.Query().Get("FilePath")]
			if !ok {
				http.NotFound(w, r)
				return
			}
			serveRange(w, r, body)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dest := t.TempDir()
	spec := Spec{Source: "modelscope", Repo: "o/r", Endpoint: srv.URL, Raw: map[string]any{}}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(dest, "model.safetensors")); string(b) != "msdata" {
		t.Fatalf("ms content = %q", b)
	}
}

func TestModelScopeRevisionAttempts(t *testing.T) {
	if got := msRevisionAttempts("main"); len(got) != 2 || got[0] != "master" || got[1] != "" {
		t.Fatalf("main -> %v", got)
	}
	if got := msRevisionAttempts(""); len(got) != 1 || got[0] != "" {
		t.Fatalf("empty -> %v", got)
	}
	if got := msRevisionAttempts("v1"); len(got) != 2 || got[0] != "v1" || got[1] != "" {
		t.Fatalf("v1 -> %v", got)
	}
}

func TestModelScopeRevisionFallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/models/o/r/repo/files":
			if r.URL.Query().Get("Revision") == "master" {
				http.NotFound(w, r)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"Code": 200, "Data": map[string]any{
				"Files": []map[string]any{{"Path": "model.safetensors", "Type": "blob", "Size": 4}},
			}})
		case "/api/v1/models/o/r/repo":
			serveRange(w, r, "ms22")
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dest := t.TempDir()
	spec := Spec{Source: "modelscope", Repo: "o/r", Revision: "main", Endpoint: srv.URL, Raw: map[string]any{}}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(dest, "model.safetensors")); string(b) != "ms22" {
		t.Fatalf("fallback content = %q", b)
	}
}

// TestLiveHuggingFaceMirror exercises the real Hub API. Skipped unless
// FLASHCLI_LIVE_HF=1 (set the endpoint with FLASHCLI_LIVE_HF_ENDPOINT).
func TestLiveHuggingFaceMirror(t *testing.T) {
	if os.Getenv("FLASHCLI_LIVE_HF") == "" {
		t.Skip("set FLASHCLI_LIVE_HF=1 to run the live Hub test")
	}
	endpoint := envOr("FLASHCLI_LIVE_HF_ENDPOINT", "https://hf-mirror.com")
	dest := t.TempDir()
	spec := Spec{
		Source:        "huggingface",
		Repo:          "hf-internal-testing/tiny-random-gpt2",
		Revision:      "main",
		Endpoint:      endpoint,
		AllowPatterns: []string{"config.json"},
		Raw:           map[string]any{},
	}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dest, "config.json")); err != nil {
		t.Fatalf("config.json missing: %v", err)
	}
}

// TestLiveModelScope exercises the real ModelScope API. Skipped unless
// FLASHCLI_LIVE_MS=1.
func TestLiveModelScope(t *testing.T) {
	if os.Getenv("FLASHCLI_LIVE_MS") == "" {
		t.Skip("set FLASHCLI_LIVE_MS=1 to run the live ModelScope test")
	}
	endpoint := envOr("FLASHCLI_LIVE_MS_ENDPOINT", "https://www.modelscope.cn")
	dest := t.TempDir()
	spec := Spec{
		Source:        "modelscope",
		Repo:          "lerobot/pi05_libero_finetuned_v044",
		Revision:      "main",
		Endpoint:      endpoint,
		AllowPatterns: []string{"config.json"},
		Raw:           map[string]any{},
	}
	if err := Download(context.Background(), spec, dest, true); err != nil {
		t.Fatalf("Download: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dest, "config.json")); err != nil {
		t.Fatalf("config.json missing: %v", err)
	}
}

// --- helpers ---------------------------------------------------------------

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func serveRange(w http.ResponseWriter, r *http.Request, body string) {
	rng := r.Header.Get("Range")
	if rng == "" {
		w.Header().Set("Content-Length", strconv.Itoa(len(body)))
		_, _ = w.Write([]byte(body))
		return
	}
	var start int
	_, _ = fmt.Sscanf(rng, "bytes=%d-", &start)
	if start > len(body) {
		w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
		return
	}
	w.Header().Set("Content-Range", "bytes "+strconv.Itoa(start)+"-"+strconv.Itoa(len(body)-1)+"/"+strconv.Itoa(len(body)))
	w.WriteHeader(http.StatusPartialContent)
	_, _ = w.Write([]byte(body[start:]))
}
