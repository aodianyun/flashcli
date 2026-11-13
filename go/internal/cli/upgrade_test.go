package cli

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func sha256hex(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func TestUpgradeInstallsVerifiedBinary(t *testing.T) {
	payload := []byte("#!/bin/sh\necho hi\n")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	target := filepath.Join(t.TempDir(), "flashcli")
	if err := os.WriteFile(target, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	code := Main([]string{"upgrade", "--url", srv.URL + "/bin", "--sha256", sha256hex(payload), "--target", target})
	if code != 0 {
		t.Fatalf("exit = %d", code)
	}
	got, _ := os.ReadFile(target)
	if string(got) != string(payload) {
		t.Fatalf("target not replaced: %q", got)
	}
}

func TestUpgradeRejectsBadChecksum(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("payload"))
	}))
	defer srv.Close()

	target := filepath.Join(t.TempDir(), "flashcli")
	if err := os.WriteFile(target, []byte("old"), 0o755); err != nil {
		t.Fatal(err)
	}
	code := Main([]string{"upgrade", "--url", srv.URL, "--sha256", "deadbeef", "--target", target})
	if code == 0 {
		t.Fatal("expected non-zero exit")
	}
	if got, _ := os.ReadFile(target); string(got) != "old" {
		t.Fatalf("target should be untouched: %q", got)
	}
}

func TestUpgradeRequiresChecksumUnlessInsecure(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("payload"))
	}))
	defer srv.Close()

	target := filepath.Join(t.TempDir(), "flashcli")
	if code := Main([]string{"upgrade", "--url", srv.URL, "--target", target}); code == 0 {
		t.Fatal("expected refusal without checksum")
	}
	if code := Main([]string{"upgrade", "--url", srv.URL, "--insecure", "--target", target}); code != 0 {
		t.Fatalf("insecure install exit = %d", code)
	}
}

func TestReleaseDefaultsFollowMirrorMode(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("FLASHCLI_USE_MIRROR", "1")
	t.Setenv("FLASHCLI_NO_MIRROR", "")
	base, api := releaseDefaults()
	if base != giteeReleaseBase || api != giteeReleaseAPI {
		t.Fatalf("mirror defaults = %q %q", base, api)
	}

	t.Setenv("FLASHCLI_USE_MIRROR", "")
	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	base, api = releaseDefaults()
	if base != defaultReleaseBase || api != defaultReleaseAPI {
		t.Fatalf("non-mirror defaults = %q %q", base, api)
	}
}

func TestReleaseDefaultsUseMirrorEnvFile(t *testing.T) {
	home := t.TempDir()
	if err := os.WriteFile(filepath.Join(home, "mirror.env"), []byte("FLASHCLI_USE_MIRROR=1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("FLASHCLI_USE_MIRROR", "")
	t.Setenv("FLASHCLI_NO_MIRROR", "")
	base, api := releaseDefaults()
	if base != giteeReleaseBase || api != giteeReleaseAPI {
		t.Fatalf("mirror.env defaults = %q %q", base, api)
	}
}
