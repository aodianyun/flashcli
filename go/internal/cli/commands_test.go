package cli

import (
	"path/filepath"
	"testing"
)

func TestVersionCmd(t *testing.T) {
	if code := Main([]string{"version"}); code != 0 {
		t.Fatalf("version exit = %d", code)
	}
}

func TestDoctorCmd(t *testing.T) {
	// 0 when every probe is satisfied, 1 when a probe is missing — never a crash.
	if code := Main([]string{"doctor"}); code != 0 && code != 1 {
		t.Fatalf("doctor exit = %d", code)
	}
}

func TestModelsEnvsLocal(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle := filepath.Join(home, "demo_exec")
	writeExecBundle(t, bundle)
	if code := Main([]string{"models", "envs", bundle}); code != 0 {
		t.Fatalf("models envs exit = %d", code)
	}
}

func TestBundleInstallNativeOnly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	bundle := filepath.Join(home, "demo_exec")
	writeExecBundle(t, bundle)
	// Native-only bundles have no Python deps; install must not build a venv.
	if code := Main([]string{"bundle", "install", bundle}); code != 0 {
		t.Fatalf("bundle install exit = %d", code)
	}
}

func TestPullBadRef(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"pull", "/no/such/bundle/path"}); code == 0 {
		t.Fatal("pull on a missing ref should fail")
	}
}

func TestWeightsPullBadPath(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	if code := Main([]string{"weights", "pull", "/no/such/bundle"}); code != 1 {
		t.Fatalf("weights pull exit = %d, want 1", code)
	}
}
