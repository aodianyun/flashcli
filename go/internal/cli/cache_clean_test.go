package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
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

func writeCacheFixture(t *testing.T, home string) (bundle, weights string) {
	t.Helper()
	for _, area := range []string{"cache", "python", "tools", "runtimes"} {
		writeCacheFile(t, filepath.Join(home, area, "marker.bin"))
	}
	bundle = filepath.Join(home, "bundles", "demo", "1.0.0", "flashcli-bundle.json")
	weights = filepath.Join(home, "models", "demo", "1.0.0", "weights.bin")
	writeCacheFile(t, bundle)
	writeCacheFile(t, weights)
	return bundle, weights
}

func TestCacheCleanDefaultSharedCache(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle, weights := writeCacheFixture(t, home)

	if code := Main([]string{"cache", "clean", "--yes"}); code != 0 {
		t.Fatalf("exit = %d", code)
	}
	for _, area := range []string{"cache", "python", "tools"} {
		if _, err := os.Stat(filepath.Join(home, area)); err == nil {
			t.Fatalf("shared cache area %s not removed", area)
		}
	}
	if _, err := os.Stat(filepath.Join(home, "runtimes")); err != nil {
		t.Fatalf("default clean must keep runtimes: %v", err)
	}
	for _, p := range []string{bundle, weights} {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("cache clean must not touch %s: %v", p, err)
		}
	}
}

func TestCacheCleanConfirmation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	cache := filepath.Join(home, "cache", "marker")
	writeCacheFile(t, cache)

	run := func(answer string) (string, error) {
		cmd := New()
		var out bytes.Buffer
		cmd.SetOut(&out)
		cmd.SetErr(&out)
		cmd.SetIn(strings.NewReader(answer))
		cmd.SetArgs([]string{"cache", "clean"})
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
	if _, err := os.Stat(filepath.Join(home, "cache")); err != nil {
		t.Fatal("declining confirmation must keep shared cache")
	}
	if _, err := run("y\n"); err != nil {
		t.Fatalf("confirm execute: %v", err)
	}
	if _, err := os.Stat(filepath.Join(home, "cache")); err == nil {
		t.Fatal("confirming must remove shared cache")
	}
}

func TestCacheCleanRejectsArgs(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"cache", "clean", "some-ref"}); code == 0 {
		t.Fatal("cache clean must reject a ref argument")
	}
}
