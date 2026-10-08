package nativeabi

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
)

func TestV1BaseSize(t *testing.T) {
	// x86_64 v1 baseline ends after `release` (offset 120 + 8).
	if V1BaseSize != 128 {
		t.Fatalf("V1BaseSize = %d, want 128", V1BaseSize)
	}
}

func TestSpecFromEntry(t *testing.T) {
	entry := &manifest.EntrySpec{Kind: "native-abi", Native: map[string]any{
		"library": "{runtime_dir}/libx.so", "preload": []any{"a.so", "b.so"},
	}}
	spec, err := SpecFromEntry(entry)
	if err != nil {
		t.Fatal(err)
	}
	if spec.OpenSymbol != DefaultOpenSymbol || len(spec.Preload) != 2 {
		t.Fatalf("unexpected spec: %+v", spec)
	}
}

func TestResolveGlobErrors(t *testing.T) {
	ph := nativeexec.Placeholders{}
	if _, err := resolveGlob(ph, "/no/such/dir/*.so"); err == nil {
		t.Fatal("expected no-match error")
	}
	dir := t.TempDir()
	for _, name := range []string{"a.so", "b.so"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := resolveGlob(ph, filepath.Join(dir, "*.so")); err == nil {
		t.Fatal("expected ambiguous error")
	}
}

func TestOpenABIEcho(t *testing.T) {
	cc := lookCC()
	if cc == "" {
		t.Skip("no C compiler available")
	}
	dirs := strings.Split(envOr("FLASHRT_INCLUDE_DIRS", "/app/FlashRT/runtime/include:/app/FlashRT/exec/include"), ":")
	includeArgs := make([]string, 0, len(dirs))
	for _, d := range dirs {
		if d != "" {
			includeArgs = append(includeArgs, "-I"+d)
		}
	}
	header := filepath.Join(dirs[0], "flashrt", "model_runtime.h")
	if _, err := os.Stat(header); err != nil {
		t.Skipf("FlashRT header not found at %s", header)
	}

	src, err := filepath.Abs(filepath.Join("..", "..", "..", "tests", "conformance", "fixtures", "abi_echo", "src", "abi_echo.c"))
	if err != nil {
		t.Fatal(err)
	}
	so := filepath.Join(t.TempDir(), "libabi_echo.so")
	args := append([]string{"-shared", "-fPIC", "-o", so, src}, includeArgs...)
	if out, err := exec.Command(cc, args...).CombinedOutput(); err != nil {
		t.Fatalf("cc: %v\n%s", err, out)
	}

	spec := Spec{
		Library:    so,
		OpenSymbol: DefaultOpenSymbol,
		Config:     map[string]any{"precision": "{option:precision}"},
	}
	ph := nativeexec.Placeholders{Options: map[string]string{"precision": "fp16"}}
	lib, err := Open(spec, ph)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer lib.Close()

	if lib.ABIVersion != 1 {
		t.Fatalf("abi_version = %d", lib.ABIVersion)
	}
	if lib.StructSize < uint32(V1BaseSize) {
		t.Fatalf("struct_size = %d < %d", lib.StructSize, V1BaseSize)
	}
	if lib.ConfigJSON() != `{"precision":"fp16"}` {
		t.Fatalf("config = %s", lib.ConfigJSON())
	}
}

func lookCC() string {
	for _, name := range []string{"cc", "gcc"} {
		if p, err := exec.LookPath(name); err == nil {
			return p
		}
	}
	return ""
}

func envOr(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}
