package server

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTailFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "model.log")
	blob := "one\ntwo\nthree\nfour\n"
	if err := os.WriteFile(path, []byte(blob), 0o644); err != nil {
		t.Fatal(err)
	}
	lines, err := tailFile(path, 2)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(lines, ","); got != "three,four" {
		t.Fatalf("lines = %q", got)
	}
}

func TestServeLogName(t *testing.T) {
	got := serveLogName("flashcli-bundle/qwen3:1.0.0")
	want := "flashcli-bundle_qwen3_1.0.0.log"
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestServerLogRing(t *testing.T) {
	logRingMu.Lock()
	logRing = nil
	logRingMu.Unlock()
	w := LogSink()
	for _, line := range []string{"a", "b", "c"} {
		if _, err := w.Write([]byte(line + "\n")); err != nil {
			t.Fatal(err)
		}
	}
	lines := serverLogLines(2)
	if got := strings.Join(lines, ","); got != "b,c" {
		t.Fatalf("lines = %q", got)
	}
}
