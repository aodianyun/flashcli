package venv

import (
	"strings"
	"testing"
)

func TestFlashcliBundleSpecOverride(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "/tmp/bundle[infer]")
	spec, err := FlashcliBundleSpec()
	if err != nil || spec != "/tmp/bundle[infer]" {
		t.Fatalf("spec = %q, err = %v", spec, err)
	}
}

func TestFlashcliBundleSpecGitDefault(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "")
	t.Setenv("FLASHCLI_INSTALL_REPO", "")
	t.Setenv("FLASHCLI_INSTALL_REF", "")
	// Run from a dir with no local flashcli-bundle checkout.
	t.Chdir(t.TempDir())
	spec, err := FlashcliBundleSpec()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(spec, "git+https://github.com/aodianyun/flashcli.git@main") ||
		!strings.Contains(spec, "subdirectory=flashcli-bundle") {
		t.Fatalf("spec = %q", spec)
	}
}

func TestFlashcliBundleSpecInstallRepo(t *testing.T) {
	t.Setenv("FLASHCLI_BUNDLE_PIP_SPEC", "")
	t.Setenv("FLASHCLI_INSTALL_REPO", "https://gitee.com/aodiansoft/flashcli.git")
	t.Setenv("FLASHCLI_INSTALL_REF", "v1.2.3")
	t.Chdir(t.TempDir())
	spec, err := FlashcliBundleSpec()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(spec, "gitee.com/aodiansoft/flashcli.git@v1.2.3") {
		t.Fatalf("spec = %q", spec)
	}
}
