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
