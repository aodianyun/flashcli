package selfupdate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestParseChecksums(t *testing.T) {
	text := "abc123  flashcli-linux-amd64\nDEF456 *flashcli-linux-arm64\n\ngarbage\n"
	sums := ParseChecksums(text)
	if sums["flashcli-linux-amd64"] != "abc123" {
		t.Fatalf("amd64 = %q", sums["flashcli-linux-amd64"])
	}
	if sums["flashcli-linux-arm64"] != "def456" {
		t.Fatalf("arm64 = %q", sums["flashcli-linux-arm64"])
	}
}

func TestVerify(t *testing.T) {
	data := []byte("hello")
	sum := sha256.Sum256(data)
	hexsum := hex.EncodeToString(sum[:])
	if err := Verify(data, hexsum); err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if err := Verify(data, "deadbeef"); err == nil {
		t.Fatal("expected mismatch")
	}
}

func TestReplace(t *testing.T) {
	target := filepath.Join(t.TempDir(), "flashcli")
	if err := os.WriteFile(target, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Replace(target, []byte("new")); err != nil {
		t.Fatalf("Replace: %v", err)
	}
	got, _ := os.ReadFile(target)
	if string(got) != "new" {
		t.Fatalf("content = %q", got)
	}
	info, _ := os.Stat(target)
	if info.Mode().Perm()&0o111 == 0 {
		t.Fatalf("not executable: %v", info.Mode())
	}
}

func TestReleaseURL(t *testing.T) {
	got := ReleaseURL("https://example.com/dl/", "v1.2.3", "flashcli-linux-amd64")
	want := "https://example.com/dl/v1.2.3/flashcli-linux-amd64"
	if got != want {
		t.Fatalf("ReleaseURL = %q", got)
	}
}

func TestLatestVersion(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name":"v0.9.9","name":"x"}`))
	}))
	defer srv.Close()
	got, err := LatestVersion(context.Background(), srv.Client(), srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	if got != "0.9.9" {
		t.Fatalf("version = %q", got)
	}
}
