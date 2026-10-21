package uv

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

// Opt-in: FLASHCLI_UV_TEST=1 (needs the PyPI mirror).
func TestProvisionIntegration(t *testing.T) {
	if os.Getenv("FLASHCLI_UV_TEST") != "1" {
		t.Skip("set FLASHCLI_UV_TEST=1 to provision uv from the index")
	}
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	t.Setenv("PIP_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")
	t.Setenv("FLASHCLI_UV_VERSION", "")
	ctx := context.Background()
	ver := latestVersion(ctx, true)
	if ver == "" {
		t.Fatal("no uv version found on the index")
	}
	bin, err := Provision(ctx, ver, true)
	if err != nil {
		t.Fatal(err)
	}
	if want := filepath.Join(home, "tools", "uv", ver, "uv"); bin != want {
		t.Fatalf("provisioned %q want %q", bin, want)
	}
	got, err := Version(ctx, bin)
	if err != nil || !AtLeast(got, MinVersion) {
		t.Fatalf("version %q err %v", got, err)
	}
}
