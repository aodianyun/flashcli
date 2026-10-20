package weights

import (
	"context"
	"errors"
	"os"
	"path/filepath"
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
		func() error { called = true; return errors.New("network") })
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
		func() error { called = true; return errors.New("network") })
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
		func() error {
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
		func() error {
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
