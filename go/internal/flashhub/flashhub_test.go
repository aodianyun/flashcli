package flashhub

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWantFile(t *testing.T) {
	env := "runtime/sm120-cu130-linux-x86_64-py310"
	all := []string{
		env,
		"runtime/sm89-cu124-linux-x86_64-py310",
		"runtime/shared-cell",
	}
	cases := map[string]bool{
		"flashcli-bundle.json": true,
		"run.py":               true,
		"flash_rt/api.py":      true,
		"runtime/sm120-cu130-linux-x86_64-py310/lib.so": true,
		"runtime/sm89-cu124-linux-x86_64-py310/lib.so":  false,
		"runtime/shared-cell/lib.so":                    false,
	}
	for path, want := range cases {
		if got := WantFile(path, env, all); got != want {
			t.Fatalf("WantFile(%q) = %v, want %v", path, got, want)
		}
	}
}

func TestWantFileArbitraryRuntime(t *testing.T) {
	selected := "sm120-cu130-linux-x86_64-py312"
	all := []string{"sm89-cu124-linux-x86_64-py312", selected}
	cases := map[string]bool{
		"flashcli-bundle.json":                  true,
		"sm120-cu130-linux-x86_64-py312/run.py": true,
		"sm120-cu130-linux-x86_64-py312/a.so":   true,
		"sm89-cu124-linux-x86_64-py312/run.py":  false,
		"common/README.md":                      true,
		"runtime/legacy-cell/a.so":              false,
	}
	for path, want := range cases {
		if got := WantFile(path, selected, all); got != want {
			t.Fatalf("WantFile(%q) = %v, want %v", path, got, want)
		}
	}
	if !WantFile("sm120-cu130-linux-x86_64-py312x/a.so", selected, all) {
		t.Fatal("prefix match must require a path boundary")
	}
}

func TestRepoURL(t *testing.T) {
	got, err := RepoURL("https://api.example/api/v1/repos/", "flashcli-bundle", "pi05_libero", "1.0.4")
	if err != nil {
		t.Fatal(err)
	}
	want := "https://api.example/api/v1/repos/flashcli-bundle/pi05_libero:1.0.4"
	if got != want {
		t.Fatalf("RepoURL = %q", got)
	}
	if _, err := RepoURL("", "", "x", "1"); err == nil {
		t.Fatal("expected error for empty namespace")
	}
}

func TestPathFromDownloadURL(t *testing.T) {
	cases := map[string]string{
		"https://cdn.example/repo/12/versions/3/runtime/sm89/lib+fa2.so": "runtime/sm89/lib+fa2.so",
		"https://cdn.example/flashcli-bundle.json":                       "flashcli-bundle.json",
	}
	for in, want := range cases {
		if got := pathFromDownloadURL(in); got != want {
			t.Fatalf("pathFromDownloadURL(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFetchIndexAndDownloadManifest(t *testing.T) {
	manifest := []byte(`{"name":"demo"}`)
	sum := md5.Sum(manifest)
	md5hex := hex.EncodeToString(sum[:])

	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	defer srv.Close()

	mux.HandleFunc("/index", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": 0,
			"data": map[string]any{"files": []map[string]any{
				{
					"download_url": srv.URL + "/repo/1/versions/2/flashcli-bundle.json",
					"file_name":    "flashcli-bundle.json",
					"file_size":    len(manifest),
					"md5_hash":     md5hex,
				},
				{
					"download_url": srv.URL + "/repo/1/versions/2/runtime/x/lib.so",
					"file_name":    "lib.so",
					"file_size":    2,
					"md5_hash":     "",
				},
			}},
		})
	})
	mux.HandleFunc("/repo/1/versions/2/flashcli-bundle.json", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(manifest)
	})

	client := &Client{HTTP: srv.Client(), CacheDir: t.TempDir(), UserAgent: "test"}
	ix, err := client.FetchIndex(context.Background(), srv.URL+"/index", true)
	if err != nil {
		t.Fatalf("FetchIndex: %v", err)
	}
	if len(ix.Files) != 2 || ix.Files[0].Path != "flashcli-bundle.json" {
		t.Fatalf("files = %+v", ix.Files)
	}
	if f := ix.Find("flashcli-bundle.json"); f == nil || f.MD5 != md5hex {
		t.Fatalf("Find manifest = %+v", f)
	}
	if f := ix.Find("lib.so"); f == nil || f.Path != "runtime/x/lib.so" {
		t.Fatalf("Find by basename = %+v", f)
	}

	dest := filepath.Join(t.TempDir(), "manifest.json")
	data, err := client.DownloadManifest(context.Background(), srv.URL+"/index", dest, false, true)
	if err != nil {
		t.Fatalf("DownloadManifest: %v", err)
	}
	if data["name"] != "demo" {
		t.Fatalf("manifest = %v", data)
	}
}

func TestDownloadFileMD5Mismatch(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("payload"))
	}))
	defer srv.Close()

	client := &Client{HTTP: srv.Client()}
	dest := filepath.Join(t.TempDir(), "f.bin")
	err := client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL, MD5: "deadbeef"}, dest, true, true, nil)
	if err == nil {
		t.Fatal("expected md5 mismatch")
	}
	if _, statErr := os.Stat(dest); statErr == nil {
		t.Fatal("dest should not exist after mismatch")
	}
}

func TestWantFileSharedRuntime(t *testing.T) {
	shared := "runtime/shared"
	all := []string{shared, "runtime/other"}
	if !WantFile("runtime/shared/lib.so", shared, all) {
		t.Fatal("selected shared runtime must be synced")
	}
	if !WantFile("runtime/shared/substrate/lib.so", shared, all) {
		t.Fatal("nested files under selected shared runtime must be synced")
	}
	if WantFile("runtime/other/lib.so", shared, all) {
		t.Fatal("unselected runtime must not be synced")
	}
}

func TestSyncBundleArbitraryRuntimeIsolation(t *testing.T) {
	files := map[string]string{
		"flashcli-bundle.json": `{"name":"demo"}`,
		"common/README.md":     "common",
		"env-a/run.py":         "a",
		"env-a/kernels.so":     "a-so",
		"env-b/run.py":         "b",
		"env-b/kernels.so":     "b-so",
		"runtime/other/x.so":   "other",
	}
	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	defer srv.Close()
	mux.HandleFunc("/index", func(w http.ResponseWriter, r *http.Request) {
		var entries []map[string]any
		for path, body := range files {
			entries = append(entries, map[string]any{
				"download_url": srv.URL + "/repo/1/versions/1/" + path,
				"file_name":    filepath.Base(path),
				"file_size":    len(body),
				"md5_hash":     "",
			})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": 0,
			"data": map[string]any{"files": entries},
		})
	})
	mux.HandleFunc("/repo/1/versions/1/", func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/repo/1/versions/1/")
		body, ok := files[path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(body))
	})

	client := &Client{HTTP: srv.Client(), CacheDir: t.TempDir(), UserAgent: "test"}
	bundleDir := t.TempDir()
	if _, err := client.SyncBundle(
		context.Background(), srv.URL+"/index", bundleDir, "env-a", []string{"env-a", "env-b"}, true,
	); err != nil {
		t.Fatalf("SyncBundle: %v", err)
	}
	for _, rel := range []string{"flashcli-bundle.json", "common/README.md", "env-a/run.py", "env-a/kernels.so"} {
		if _, err := os.Stat(filepath.Join(bundleDir, filepath.FromSlash(rel))); err != nil {
			t.Fatalf("expected %s: %v", rel, err)
		}
	}
	for _, rel := range []string{"env-b/run.py", "env-b/kernels.so", "runtime/other/x.so"} {
		if _, err := os.Stat(filepath.Join(bundleDir, filepath.FromSlash(rel))); err == nil {
			t.Fatalf("unexpected %s", rel)
		}
	}
}
