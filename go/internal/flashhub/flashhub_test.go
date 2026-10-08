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
	"testing"
)

func TestWantFile(t *testing.T) {
	env := "sm120-cu130-linux-x86_64-py310"
	cases := map[string]bool{
		"flashcli-bundle.json": true,
		"run.py":               true,
		"flash_rt/api.py":      true,
		"runtime/sm120-cu130-linux-x86_64-py310/lib.so": true,
		"runtime/sm89-cu124-linux-x86_64-py310/lib.so":  false,
	}
	for path, want := range cases {
		if got := WantFile(path, env); got != want {
			t.Fatalf("WantFile(%q) = %v, want %v", path, got, want)
		}
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
	err := client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL, MD5: "deadbeef"}, dest, true, true)
	if err == nil {
		t.Fatal("expected md5 mismatch")
	}
	if _, statErr := os.Stat(dest); statErr == nil {
		t.Fatal("dest should not exist after mismatch")
	}
}
