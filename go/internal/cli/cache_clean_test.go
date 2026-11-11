package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

func writeCacheFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestCacheCleanTargets(t *testing.T) {
	for _, tc := range []struct {
		name string
		args []string
		path string
	}{
		{"uv", []string{"--uv"}, "uv/cache-marker"},
		{"tools", []string{"--tools"}, "tools/uv/bin/uv"},
		{"flashhub", []string{"--flashhub"}, "cache/downloads/repo-index/index.json"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("FLASHCLI_HOME", home)
			t.Setenv("UV_CACHE_DIR", filepath.Join(home, "uv"))
			target := filepath.Join(home, filepath.FromSlash(tc.path))
			writeCacheFile(t, target)
			args := append([]string{"cache", "clean"}, tc.args...)
			args = append(args, "--yes")
			if code := Main(args); code != 0 {
				t.Fatalf("exit = %d", code)
			}
			if _, err := os.Stat(filepath.Join(target, "..")); err == nil {
				t.Fatalf("expected parent cache to be removed, target=%s", target)
			}
		})
	}
}

func TestCacheCleanAll(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("UV_CACHE_DIR", filepath.Join(home, "uv"))
	targets := []string{
		filepath.Join(home, "uv", "marker"),
		filepath.Join(home, "tools", "uv", "bin", "uv"),
		filepath.Join(home, "cache", "downloads", "repo-index", "index.json"),
	}
	for _, p := range targets {
		writeCacheFile(t, p)
	}
	if code := Main([]string{"cache", "clean", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	for _, p := range []string{
		filepath.Join(home, "uv"),
		filepath.Join(home, "tools", "uv"),
		filepath.Join(home, "cache", "downloads", "repo-index"),
	} {
		if _, err := os.Stat(p); err == nil {
			t.Fatalf("expected %s removed", p)
		}
	}
}

func TestCacheCleanAllStaysPackageScoped(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("UV_CACHE_DIR", filepath.Join(home, "uv"))
	for _, p := range []string{
		filepath.Join(home, "uv", "marker"),
		filepath.Join(home, "tools", "uv", "bin", "uv"),
		filepath.Join(home, "cache", "downloads", "repo-index", "index.json"),
		filepath.Join(home, "cache", "downloads", "file.bin"),
		filepath.Join(home, "python", "bin", "python3"),
		filepath.Join(home, "runtimes", "rt", "torch.bin"),
		filepath.Join(home, "bundles", "demo", "1.0.0", "flashcli-bundle.json"),
		filepath.Join(home, "models", "demo", "1.0.0", "weights.bin"),
	} {
		writeCacheFile(t, p)
	}
	if code := Main([]string{"cache", "clean", "--all", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	for _, p := range []string{
		filepath.Join(home, "cache", "downloads", "file.bin"),
		filepath.Join(home, "python"),
		filepath.Join(home, "runtimes"),
		filepath.Join(home, "bundles"),
		filepath.Join(home, "models"),
	} {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("--all must keep %s outside package caches: %v", p, err)
		}
	}
}

func TestCacheCleanStorageMatchesServerTargets(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("UV_CACHE_DIR", filepath.Join(home, "cache", "uv"))
	targets := []string{
		filepath.Join(home, "cache", "downloads", "file.bin"),
		filepath.Join(home, "python", "bin", "python3"),
		filepath.Join(home, "tools", "uv", "bin", "uv"),
		filepath.Join(home, "runtimes", "rt", "torch.bin"),
	}
	for _, p := range targets {
		writeCacheFile(t, p)
	}
	bundle := filepath.Join(home, "bundles", "demo", "1.0.0", "flashcli-bundle.json")
	weights := filepath.Join(home, "models", "demo", "1.0.0", "weights.bin")
	writeCacheFile(t, bundle)
	writeCacheFile(t, weights)
	if code := Main([]string{"cache", "clean", "--storage", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	for _, p := range []string{
		filepath.Join(home, "cache"),
		filepath.Join(home, "python"),
		filepath.Join(home, "tools"),
		filepath.Join(home, "runtimes"),
	} {
		if _, err := os.Stat(p); err == nil {
			t.Fatalf("expected storage area %s removed", p)
		}
	}
	for _, p := range []string{bundle, weights} {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("storage clean must not touch %s: %v", p, err)
		}
	}
}

func TestCacheCleanConfirmation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	cache := filepath.Join(home, "uv")
	t.Setenv("UV_CACHE_DIR", cache)
	writeCacheFile(t, filepath.Join(cache, "marker"))

	run := func(answer string) (string, error) {
		cmd := New()
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetErr(&out)
		cmd.SetIn(strings.NewReader(answer))
		cmd.SetArgs([]string{"cache", "clean", "--uv"})
		err := cmd.Execute()
		return out.String(), err
	}

	out, err := run("n\n")
	if err != nil {
		t.Fatalf("abort execute: %v", err)
	}
	if !strings.Contains(out, "Continue? [y/N]") {
		t.Fatalf("missing prompt:\n%s", out)
	}
	if _, err := os.Stat(cache); err != nil {
		t.Fatal("declining confirmation must keep uv cache")
	}
	if _, err := run("y\n"); err != nil {
		t.Fatalf("confirm execute: %v", err)
	}
	if _, err := os.Stat(cache); err == nil {
		t.Fatal("confirming must remove uv cache")
	}
}

func TestCacheCleanNoSelection(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"cache", "clean"}); code == 0 {
		t.Fatal("cache clean without a target must fail")
	}
}

func TestCacheCleanUsesConfiguredUVPath(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	custom := filepath.Join(home, "custom-uv")
	t.Setenv("UV_CACHE_DIR", custom)
	writeCacheFile(t, filepath.Join(custom, "marker"))
	if code := Main([]string{"cache", "clean", "--uv", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	if _, err := os.Stat(custom); err == nil {
		t.Fatal("UV_CACHE_DIR target must be removed")
	}
	if _, err := os.Stat(paths.Bundles()); err == nil {
		t.Fatal("cache clean must not touch bundles")
	}
}
