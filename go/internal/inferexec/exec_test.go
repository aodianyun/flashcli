package inferexec

import (
	"strings"
	"testing"
)

func TestBuildArgv(t *testing.T) {
	got := BuildArgv("/v/bin/python", "run", []string{"--prompt", "hi"})
	want := []string{"/v/bin/python", "-m", "flashcli_bundle.infer", "run", "--prompt", "hi"}
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("argv = %v", got)
	}
}

func TestBuildEnvStripsAndSets(t *testing.T) {
	base := []string{
		"PATH=/usr/bin",
		"PYTHONPATH=/host/src",
		"PYTHONSAFEPATH=1",
		"HF_HUB_OFFLINE=0",
		"FLASHCLI_RUNTIME_ID=stale",
		"FOO=bar",
	}
	env := BuildEnv(base, "b-local-abc", "/bundle", "/rt/venv")
	joined := strings.Join(env, "\n")

	for _, banned := range []string{"PYTHONPATH=", "PYTHONSAFEPATH=", "FLASHCLI_RUNTIME_ID=stale", "HF_HUB_OFFLINE=0"} {
		if strings.Contains(joined, banned) {
			t.Fatalf("env should not contain %q:\n%s", banned, joined)
		}
	}
	for _, want := range []string{
		"FOO=bar",
		"HF_HUB_OFFLINE=1",
		"FLASHCLI_IN_BUNDLE_VENV=1",
		"FLASHCLI_RUNTIME_ID=b-local-abc",
		"FLASHCLI_BUNDLE_ROOT=/bundle",
		"VIRTUAL_ENV=/rt/venv",
	} {
		if !strings.Contains(joined, want) {
			t.Fatalf("env missing %q:\n%s", want, joined)
		}
	}
}
