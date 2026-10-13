package pythonprovision

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeExecutable(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
}

func TestResolveEnvOverride(t *testing.T) {
	dir := t.TempDir()
	py := filepath.Join(dir, "python3.10")
	writeExecutable(t, py, "#!/bin/sh\necho \"(3, 10)\"\n")
	t.Setenv("FLASHCLI_PY310_BIN", py)
	got, ok := Resolve("310")
	if !ok || got != py {
		t.Fatalf("Resolve = %q, %v", got, ok)
	}
}

func TestAssetFromManifestFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "python-standalone.json")
	body := `{"files":[{"py_minor":"310","triplet":"x86_64-unknown-linux-gnu","tag":"20260602","filename":"cpython-3.10.0+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz","url":"https://example/x.tar.gz","md5":"abc"}]}`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	asset, err := assetFromManifestFile(path, "310", "x86_64-unknown-linux-gnu")
	if err != nil {
		t.Fatal(err)
	}
	if asset.Filename == "" || asset.URL != "https://example/x.tar.gz" || asset.MD5 != "abc" {
		t.Fatalf("asset = %+v", asset)
	}
}

func makeTarGz(t *testing.T, entries map[string]string, symlinks map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	write := func(name string, mode int64, typeflag byte, content, link string) {
		if err := tw.WriteHeader(&tar.Header{
			Name: name, Mode: mode, Typeflag: typeflag, Size: int64(len(content)), Linkname: link,
		}); err != nil {
			t.Fatal(err)
		}
		if len(content) > 0 {
			if _, err := tw.Write([]byte(content)); err != nil {
				t.Fatal(err)
			}
		}
	}
	for name, content := range entries {
		write(name, 0o755, tar.TypeReg, content, "")
	}
	for name, link := range symlinks {
		write(name, 0o777, tar.TypeSymlink, "", link)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// TestLiveFlashHubStandalone resolves a real FlashHub standalone asset (no
// tarball download). Skipped unless FLASHCLI_LIVE_PYTHON=1.
func TestLiveFlashHubStandalone(t *testing.T) {
	if os.Getenv("FLASHCLI_LIVE_PYTHON") == "" {
		t.Skip("set FLASHCLI_LIVE_PYTHON=1 to hit the real FlashHub python-standalone repo")
	}
	asset, err := ResolveAsset(context.Background(), "312", "x86_64-unknown-linux-gnu", DefaultStandaloneTag, standaloneRepoURL())
	if err != nil {
		t.Fatalf("ResolveAsset: %v", err)
	}
	if !strings.Contains(asset.Filename, "cpython-3.12") {
		t.Fatalf("filename = %q", asset.Filename)
	}
	if asset.URL == "" {
		t.Fatalf("empty url")
	}
}

func TestInstallStandalone(t *testing.T) {
	tarball := makeTarGz(t,
		map[string]string{"python/bin/python3.10": "#!/bin/sh\necho \"(3, 10)\"\n"},
		map[string]string{"python/bin/python3": "python3.10"},
	)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(tarball)
	}))
	defer srv.Close()
	oldClient := HTTPClient
	HTTPClient = srv.Client()
	defer func() { HTTPClient = oldClient }()

	root := t.TempDir()
	t.Setenv("FLASHCLI_PYTHON_ROOT", root)
	t.Setenv("FLASHCLI_PYTHON_ENV", filepath.Join(root, "python-runtime.env"))
	t.Setenv("FLASHCLI_PYTHON_STANDALONE_URL", srv.URL+"/cpython.tar.gz")
	t.Setenv("FLASHCLI_TEST_MACHINE", "amd64")
	t.Setenv("FLASHCLI_PY310_BIN", "")

	bin, err := InstallStandalone(context.Background(), "310", true)
	if err != nil {
		t.Fatalf("InstallStandalone: %v", err)
	}
	if !reportsMinor(bin, "310") {
		t.Fatalf("installed bin does not report 3.10: %s", bin)
	}
	if _, err := os.Stat(filepath.Join(root, "python-runtime.env")); err != nil {
		t.Fatalf("env file not written: %v", err)
	}
}
