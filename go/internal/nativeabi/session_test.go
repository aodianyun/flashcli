package nativeabi

import (
	"testing"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

func entry(native map[string]any) *manifest.EntrySpec {
	return &manifest.EntrySpec{Kind: "native-abi", Native: native}
}

func TestSessionFromEntry(t *testing.T) {
	e := entry(map[string]any{
		"library":         "{runtime_dir}/substrate/libflashrt_cpp_pi05_c-*.so",
		"session_library": "{runtime_dir}/substrate/libcapsule_nexus_flashrt-*.so",
		"preload":         []any{"{runtime_dir}/substrate/libflashrt_exec-*.so"},
		"config":          map[string]any{"io": "native_v2"},
	})
	if !HasSessionLibrary(e) {
		t.Fatal("expected session lane")
	}
	spec, err := SessionFromEntry(e)
	if err != nil {
		t.Fatal(err)
	}
	if spec.ProducerLibrary == "" || spec.SessionLibrary == "" {
		t.Fatalf("libraries not parsed: %+v", spec)
	}
	if spec.LoaderSymbol != DefaultLoaderSymbol {
		t.Fatalf("loader symbol = %q, want default", spec.LoaderSymbol)
	}
	if len(spec.Preload) != 1 {
		t.Fatalf("preload = %v", spec.Preload)
	}
	if spec.Config["io"] != "native_v2" {
		t.Fatalf("config = %v", spec.Config)
	}
}

func TestSessionFromEntryCustomLoader(t *testing.T) {
	spec, err := SessionFromEntry(entry(map[string]any{
		"library":         "lib.so",
		"session_library": "capsule.so",
		"loader_symbol":   "my_loader",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if spec.LoaderSymbol != "my_loader" {
		t.Fatalf("loader = %q", spec.LoaderSymbol)
	}
}

func TestSessionFromEntryErrors(t *testing.T) {
	if _, err := SessionFromEntry(entry(map[string]any{"session_library": "capsule.so"})); err == nil {
		t.Fatal("expected error when library missing")
	}
	if _, err := SessionFromEntry(entry(map[string]any{"library": "lib.so"})); err == nil {
		t.Fatal("expected error when session_library missing")
	}
	if HasSessionLibrary(entry(map[string]any{"library": "lib.so"})) {
		t.Fatal("HasSessionLibrary should be false without session_library")
	}
}
