package cuda

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFamilyAndSonames(t *testing.T) {
	if Family("130") != "13" || Family("124") != "12" || Family("128") != "12" {
		t.Fatalf("family mapping wrong")
	}
	if got := SonamesForTag("130"); len(got) != 2 || got[0] != "libcublas.so.13" {
		t.Fatalf("sonames = %v", got)
	}
	if got := PipPackagesForTag("124"); len(got) != 2 {
		t.Fatalf("packages = %v", got)
	}
}

func TestNvidiaLibDirsAndFindSoname(t *testing.T) {
	purelib := filepath.Join(t.TempDir(), "lib", "python3.10", "site-packages")
	libDir := filepath.Join(purelib, "nvidia", "cu12", "lib")
	if err := os.MkdirAll(libDir, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(libDir, "libcublas.so.12")
	if err := os.WriteFile(target, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	dirs := NvidiaLibDirs(purelib)
	if len(dirs) == 0 || dirs[0] != libDir {
		t.Fatalf("dirs = %v", dirs)
	}
	if got := FindSoname(purelib, "libcublas.so.12"); got != target {
		t.Fatalf("FindSoname = %q, want %q", got, target)
	}
	if got := FindSoname(purelib, "libcudart.so.12"); got != "" {
		t.Fatalf("expected missing, got %q", got)
	}
}

func TestPurelibFromPythonPath(t *testing.T) {
	python := filepath.Join(t.TempDir(), "venv", "bin", "python3")
	purelib := filepath.Join(filepath.Dir(filepath.Dir(python)), "lib", "python3.10", "site-packages")
	if err := os.MkdirAll(purelib, 0o755); err != nil {
		t.Fatal(err)
	}
	if got := Purelib(python); got != purelib {
		t.Fatalf("Purelib = %q, want %q", got, purelib)
	}
}

func TestPrependLDLibraryPath(t *testing.T) {
	t.Setenv("LD_LIBRARY_PATH", "/old")
	added := PrependLDLibraryPath([]string{"/a", "/b"})
	if strings.Join(added, ",") != "/b,/a" {
		t.Fatalf("added = %v", added)
	}
	env := os.Getenv("LD_LIBRARY_PATH")
	if !strings.HasPrefix(env, "/a:/b:") || !strings.Contains(env, "/old") {
		t.Fatalf("LD_LIBRARY_PATH = %q", env)
	}
	if again := PrependLDLibraryPath([]string{"/a", "/b"}); len(again) != 0 {
		t.Fatalf("expected no re-add, got %v", again)
	}
}
