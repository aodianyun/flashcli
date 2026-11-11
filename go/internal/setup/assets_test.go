package setup

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestEnsureAssetBinariesLocal(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"flashcli", "flashserver"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("local"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	opts := Options{BinDir: dir}
	cleanup, err := ensureAssetBinaries(context.Background(), Env{OS: "linux", Arch: "amd64"}, &opts, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	cleanup()
	if opts.BinDir != dir {
		t.Fatalf("BinDir = %q", opts.BinDir)
	}
}

func TestEnsureAssetBinariesDownload(t *testing.T) {
	remote := map[string][]byte{
		"flashcli-linux-amd64-v1.0.0":    []byte("cli"),
		"flashserver-linux-amd64-v1.0.0": []byte("server"),
	}
	var sums string
	for name, data := range remote {
		sum := sha256.Sum256(data)
		sums += hex.EncodeToString(sum[:]) + "  " + name + "\n"
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1.0.0/sha256sums.txt" {
			_, _ = io.WriteString(w, sums)
			return
		}
		name := filepath.Base(r.URL.Path)
		data, ok := remote[name]
		if !ok {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(data)
	}))
	defer srv.Close()

	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	opts := Options{
		BinDir:         t.TempDir(),
		ReleaseBase:    srv.URL,
		ReleaseAPI:     srv.URL + "/api",
		ReleaseVersion: "1.0.0",
	}
	cleanup, err := ensureAssetBinaries(context.Background(), Env{OS: "linux", Arch: "amd64"}, &opts, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	local := map[string][]byte{
		"flashcli-linux-amd64":    []byte("cli"),
		"flashserver-linux-amd64": []byte("server"),
	}
	for name, want := range local {
		got, err := os.ReadFile(filepath.Join(opts.BinDir, name))
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != string(want) {
			t.Fatalf("%s = %q", name, got)
		}
	}
}
