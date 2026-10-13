package venv

import (
	"os"
	"strings"
	"testing"
)

func TestLoadInstallEnvAppliesMirrorVars(t *testing.T) {
	home := t.TempDir()
	if err := os.WriteFile(home+"/install.env", []byte(
		"export FLASHCLI_INSTALL_REPO=https://example/x.git\n"+
			"export PIP_INDEX_URL=https://mirror/pypi/simple/\n"+
			"export HF_ENDPOINT=https://hf-mirror.example\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("FLASHCLI_HOME", home)
	for _, k := range []string{"PIP_INDEX_URL", "HF_ENDPOINT"} {
		old, had := os.LookupEnv(k)
		os.Unsetenv(k)
		defer func(key, val string, ok bool) {
			if ok {
				os.Setenv(key, val)
			} else {
				os.Unsetenv(key)
			}
		}(k, old, had)
	}
	LoadInstallEnv()
	if os.Getenv("PIP_INDEX_URL") != "https://mirror/pypi/simple/" {
		t.Fatalf("PIP_INDEX_URL = %q", os.Getenv("PIP_INDEX_URL"))
	}
	if os.Getenv("HF_ENDPOINT") != "https://hf-mirror.example" {
		t.Fatalf("HF_ENDPOINT = %q", os.Getenv("HF_ENDPOINT"))
	}
}

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
