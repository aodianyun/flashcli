package weights

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func touch(t *testing.T, dir, name string, size int) {
	t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, make([]byte, size), 0o644); err != nil {
		t.Fatal(err)
	}
}

func fakeCheckpoint(t *testing.T, dir string) {
	t.Helper()
	touch(t, dir, "config.json", 2)
	touch(t, dir, "model.safetensors", 8)
}

func TestManifestMissingDetectsAbsentAndSizeMismatch(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "a", 4)
	touch(t, dir, "b", 1) // wrong size vs recorded 5
	files := []remoteFile{{Path: "a", Size: 4}, {Path: "b", Size: 5}, {Path: "c", Size: 2}}
	missing := manifestMissing(dir, files)
	if len(missing) != 2 {
		t.Fatalf("missing=%v want b and c", missing)
	}
}

// Complete manifest: run/serve accept the cache without touching the network.
func TestDownloadRemoteManifestCompleteIsOffline(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir)
	touch(t, dir, "tokenizer.json", 3)
	if err := writeDownloadManifest(dir, "repo", "rev", []remoteFile{
		{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8}, {Path: "tokenizer.json", Size: 3},
	}); err != nil {
		t.Fatal(err)
	}
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, false,
		func(bool) error { called = true; return errors.New("network") })
	if err != nil {
		t.Fatal(err)
	}
	if called {
		t.Fatal("complete manifest must not trigger a download/network")
	}
}

// Legacy cache (no manifest) on run/serve: accept via bundle readiness, offline.
func TestDownloadRemoteLegacyCacheRunsOffline(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir)
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, false,
		func(bool) error { called = true; return errors.New("network") })
	if err != nil {
		t.Fatal(err)
	}
	if called {
		t.Fatal("run/serve must not list the remote for a legacy ready cache")
	}
}

// Explicit pull (verifyRemote) always verifies against the remote file set.
func TestDownloadRemotePullVerifiesRemote(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir)
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, true,
		func(bool) error {
			called = true
			// simulate a pull completing and recording the manifest
			return writeDownloadManifest(dir, "repo", "rev", []remoteFile{
				{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8},
			})
		})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("explicit pull must verify against the remote")
	}
}

// A partial download (manifest present, files missing) must not be accepted
// even when the lenient bundle readiness would pass.
func TestDownloadRemotePartialManifestForcesDownload(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir) // bundleWeightsReady would pass
	if err := writeDownloadManifest(dir, "repo", "rev", []remoteFile{
		{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8}, {Path: "tokenizer.json", Size: 3},
	}); err != nil {
		t.Fatal(err)
	}
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, false,
		func(bool) error {
			called = true
			touch(t, dir, "tokenizer.json", 3) // "download" the missing file
			return nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("partial manifest must force a download")
	}
}

// An interrupted download leaves incompleteMarker so run/serve cannot mistake
// a partial cache for a legacy ready cache.
func TestDownloadRemoteIncompleteMarkerForcesDownload(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir) // bundleWeightsReady would pass
	if err := os.WriteFile(filepath.Join(dir, incompleteMarker), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, false,
		func(bool) error {
			called = true
			return writeDownloadManifest(dir, "repo", "rev", []remoteFile{
				{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8},
			})
		})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("incomplete marker must force a download")
	}
	if _, err := os.Stat(filepath.Join(dir, incompleteMarker)); err == nil {
		t.Fatal("incomplete marker must be removed after a successful download")
	}
}

func TestDownloadFileWithResumeZeroSize(t *testing.T) {
	p := filepath.Join(t.TempDir(), "SUCCESS")
	if err := downloadFileWithResume(context.Background(), "http://127.0.0.1:1/nope", p, 0, nil, nil); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(p)
	if err != nil || info.Size() != 0 {
		t.Fatalf("zero-size file: info=%v err=%v", info, err)
	}
}

// Reproduces the field failure: the first download fails before writing the
// manifest, leaving a readiness-passing partial cache. The next run must not
// take the legacy offline shortcut.
func TestDownloadRemoteFailedAttemptIsNotLegacyReady(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir)
	spec := Spec{Source: "huggingface", Repo: "repo"}

	err := downloadRemote(context.Background(), spec, dir, true, true,
		func(bool) error {
			// The real downloader writes the expected set before fetching files.
			if werr := writeDownloadManifest(dir, "repo", "rev", []remoteFile{
				{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8},
				{Path: "processor_config.json", Size: 5},
			}); werr != nil {
				return werr
			}
			return errors.New("HTTP 429")
		})
	if err == nil {
		t.Fatal("expected the first attempt to fail")
	}
	if _, statErr := os.Stat(filepath.Join(dir, incompleteMarker)); statErr != nil {
		t.Fatal("failed attempt must leave the incomplete marker")
	}
	if _, statErr := os.Stat(filepath.Join(dir, downloadManifestName)); statErr != nil {
		t.Fatal("failed attempt must keep the expected-set manifest")
	}

	called := false
	err = downloadRemote(context.Background(), spec, dir, true, false,
		func(bool) error {
			called = true
			touch(t, dir, "processor_config.json", 5)
			return nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("run/serve must resume, not accept the partial cache as legacy")
	}
	if _, statErr := os.Stat(filepath.Join(dir, incompleteMarker)); statErr == nil {
		t.Fatal("marker must be removed after the resumed download succeeds")
	}
}

// An explicit pull must re-list even when the local manifest is complete.
func TestDownloadRemotePullRelistsCompleteManifest(t *testing.T) {
	dir := t.TempDir()
	fakeCheckpoint(t, dir)
	if err := writeDownloadManifest(dir, "repo", "rev", []remoteFile{
		{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8},
	}); err != nil {
		t.Fatal(err)
	}
	called := false
	err := downloadRemote(context.Background(),
		Spec{Source: "huggingface", Repo: "repo"}, dir, true, true,
		func(relist bool) error {
			called = true
			if !relist {
				t.Fatal("pull must request a fresh remote listing")
			}
			return writeDownloadManifest(dir, "repo", "rev", []remoteFile{
				{Path: "config.json", Size: 2}, {Path: "model.safetensors", Size: 8},
			})
		})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("pull must re-list even with a complete manifest")
	}
}

// The expected set must be persisted before file transfer: a failed download
// still leaves a resumable manifest.
func TestHuggingFaceWritesManifestBeforeDownload(t *testing.T) {
	t.Setenv("FLASHCLI_HF_DOWNLOAD_RETRIES", "1")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasPrefix(r.URL.Path, "/api/models/repo/tree/"):
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`[{"type":"file","path":"a.bin","size":4}]`))
		case r.URL.Path == "/repo/resolve/main/a.bin":
			http.Error(w, "boom", http.StatusInternalServerError)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dest := t.TempDir()
	spec := Spec{Source: "huggingface", Repo: "repo", Revision: "main", Endpoint: srv.URL}
	if err := downloadHuggingFace(context.Background(), spec, dest, true, true); err == nil {
		t.Fatal("expected the file download to fail")
	}
	man, ok := readDownloadManifest(dest, "repo")
	if !ok || len(man.Files) != 1 || man.Files[0].Path != "a.bin" || man.Files[0].Size != 4 {
		t.Fatalf("manifest before download = %+v ok=%v", man, ok)
	}
}
