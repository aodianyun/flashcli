package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestBundleSyncFromFlashHub(t *testing.T) {
	manifestObj := map[string]any{
		"format": "flashcli-model-bundle", "format_version": 3, "protocol_version": 1,
		"name": "demo", "python_abi": "310",
		"entry": map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{
			"sm120-cu130-linux-x86_64-py310": "runtime/sm120-cu130-linux-x86_64-py310",
			"sm89-cu124-linux-x86_64-py310":  "runtime/sm89-cu124-linux-x86_64-py310",
		},
	}
	manifestBytes, _ := json.Marshal(manifestObj)
	repoFiles := map[string]string{
		"flashcli-bundle.json": string(manifestBytes),
		"run.py":               "class RunEngine: pass\n",
		"runtime/sm120-cu130-linux-x86_64-py310/lib.so": "wanted",
		"runtime/sm89-cu124-linux-x86_64-py310/lib.so":  "skipped",
	}

	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	defer srv.Close()

	mux.HandleFunc("/flashcli-bundle/demo:1.0.0", func(w http.ResponseWriter, r *http.Request) {
		files := []map[string]any{}
		for path, content := range repoFiles {
			files = append(files, map[string]any{
				"download_url": srv.URL + "/repo/1/versions/2/" + path,
				"file_name":    filepath.Base(path),
				"file_size":    len(content),
				"md5_hash":     "",
			})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"code": 0, "data": map[string]any{"files": files}})
	})
	mux.HandleFunc("/repo/1/versions/2/", func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path[len("/repo/1/versions/2/"):]
		content, ok := repoFiles[path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(content))
	})

	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("FLASHCLI_FLASHHUB_API", srv.URL)
	t.Setenv("FLASHCLI_RUNTIME_ENV_KEY", "sm120-cu130-linux-x86_64-py310")
	t.Setenv("FLASHCLI_SKIP_PREFLIGHT", "1")
	t.Setenv("FLASHCLI_SKIP_VENV_SETUP", "1")

	if code := Main([]string{"bundle", "sync", "flashcli-bundle/demo:1.0.0", "--quiet"}); code != 0 {
		t.Fatalf("sync exit = %d", code)
	}

	bundleDir := filepath.Join(home, "bundles", "demo", "1.0.0")
	for _, rel := range []string{
		"flashcli-bundle.json",
		"run.py",
		"runtime/sm120-cu130-linux-x86_64-py310/lib.so",
		".flashcli_bundle.json",
	} {
		if _, err := os.Stat(filepath.Join(bundleDir, filepath.FromSlash(rel))); err != nil {
			t.Fatalf("missing %s: %v", rel, err)
		}
	}
	if _, err := os.Stat(filepath.Join(bundleDir, "runtime/sm89-cu124-linux-x86_64-py310/lib.so")); err == nil {
		t.Fatal("non-matching runtime cell should not be synced")
	}

	// Runtime marker (.runtime.json) is written for cross-host cache interop.
	runtimes := filepath.Join(home, "runtimes")
	entries, err := os.ReadDir(runtimes)
	if err != nil || len(entries) != 1 {
		t.Fatalf("expected one runtime marker dir, got %v (%v)", entries, err)
	}
	rtMarker := filepath.Join(runtimes, entries[0].Name(), ".runtime.json")
	if _, err := os.Stat(rtMarker); err != nil {
		t.Fatalf("missing runtime marker: %v", err)
	}

	// models list reflects the synced bundle.
	if code := Main([]string{"models", "list"}); code != 0 {
		t.Fatalf("models list exit = %d", code)
	}
}
