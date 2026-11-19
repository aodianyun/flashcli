// Package architecture contains guard tests for repository-wide rules that are
// not expressible through the type system.
package architecture_test

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// frontendPatterns are behaviors that must be implemented once in a shared
// package and called by both frontends. A hit means the CLI or daemon grew a
// second implementation that can drift from the canonical one.
var frontendPatterns = []struct {
	needle string
	owner  string
}{
	{"nvidia-smi", "internal/gpu (or internal/preflight) for GPU probing"},
	{
		`strings.NewReplacer("/", "_", "\\", "_", ":", "_")`,
		"internal/modelrun.LogName for serve log names",
	},
	{"filepath.Walk(", "internal/host for cache size/cleanup walking"},
	{"filepath.WalkDir(", "internal/host for cache size/cleanup walking"},
	{".flashcli_download.incomplete", "internal/host for download readiness"},
}

func TestSharedLogicIsNotDuplicatedInFrontends(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate the test source")
	}
	goRoot := filepath.Join(filepath.Dir(file), "..", "..")
	for _, dir := range []string{"internal/cli", "internal/server"} {
		root := filepath.Join(goRoot, dir)
		entries, err := os.ReadDir(root)
		if err != nil {
			t.Fatalf("read %s: %v", root, err)
		}
		for _, entry := range entries {
			name := entry.Name()
			if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
				continue
			}
			path := filepath.Join(root, name)
			blob, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("read %s: %v", path, err)
			}
			src := string(blob)
			for _, pattern := range frontendPatterns {
				if strings.Contains(src, pattern.needle) {
					t.Errorf("%s duplicates shared logic (%q); use %s", path, pattern.needle, pattern.owner)
				}
			}
		}
	}
}
