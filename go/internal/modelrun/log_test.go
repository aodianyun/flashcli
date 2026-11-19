package modelrun

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLogNameIsShared(t *testing.T) {
	if got := LogName("xym/gemma4_e2b_it:1.0.1"); got != "xym_gemma4_e2b_it_1.0.1.log" {
		t.Fatalf("LogName = %q", got)
	}
}

func TestTailLines(t *testing.T) {
	path := filepath.Join(t.TempDir(), "serve.log")
	if err := os.WriteFile(path, []byte("one\ntwo\nthree\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	lines, err := TailLines(path, 2)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(lines, []string{"two", "three"}) {
		t.Fatalf("lines = %v", lines)
	}
	all, err := TailLines(path, 10)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(all, []string{"one", "two", "three"}) {
		t.Fatalf("lines = %v", all)
	}
}
