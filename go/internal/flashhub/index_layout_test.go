package flashhub

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestParseIndexRecordedNewLayout pins the newer FlashHub upload layout, where
// the CDN URL repeats the filename: "<logical path>/<name>/<name>". Real
// payload recorded from rsi-flashrt/qwen35_4b_nvfp4:1.0.1.
func TestParseIndexRecordedNewLayout(t *testing.T) {
	blob, err := os.ReadFile(filepath.Join("testdata", "index-new-cdn-layout.json"))
	if err != nil {
		t.Fatalf("fixture: %v", err)
	}
	ix, err := parseIndex(blob, "rsi-flashrt/qwen35_4b_nvfp4:1.0.1")
	if err != nil {
		t.Fatalf("parseIndex: %v", err)
	}
	if len(ix.Files) != 22 {
		t.Fatalf("files = %d, want 22", len(ix.Files))
	}

	want := map[string]bool{
		ManifestPath:                             true,
		"run.py":                                 true,
		"NOTICE.FlashRT":                         true,
		"LICENSE.FlashRT":                        true,
		"flash_rt/__init__.py":                   true,
		"flash_rt/models/qwen35/__init__.py":     true,
		"quant/qwen35_4b_nvfp4_gptq.safetensors": true,
		"runtime/sm120-cu130-linux-x86_64-py312/flash_rt_kernels-3a2f8e1a-sm120-cu130-linux-x86_64-py312.so": true,
	}
	got := map[string]bool{}
	for _, f := range ix.Files {
		got[f.Path] = true
	}
	for path := range want {
		if !got[path] {
			t.Fatalf("missing path %q", path)
		}
	}

	// Invariant: a filename must never be repeated as its own parent directory.
	for _, f := range ix.Files {
		segments := strings.Split(f.Path, "/")
		for i := 1; i < len(segments); i++ {
			if segments[i] == segments[i-1] {
				t.Fatalf("duplicated segment in parsed path %q (from %s)", f.Path, f.URL)
			}
		}
	}
	if f := ix.Find(ManifestPath); f == nil || f.Path != ManifestPath {
		t.Fatalf("manifest lookup = %+v", f)
	}
}
