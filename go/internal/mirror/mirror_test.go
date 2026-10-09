package mirror

import (
	"os"
	"testing"
)

func reset() { applied = false }

// unset removes env keys and restores them after the test.
func unset(t *testing.T, keys ...string) {
	t.Helper()
	type kv struct {
		key string
		val string
		had bool
	}
	saved := make([]kv, 0, len(keys))
	for _, k := range keys {
		v, ok := os.LookupEnv(k)
		saved = append(saved, kv{k, v, ok})
		os.Unsetenv(k)
	}
	t.Cleanup(func() {
		for _, s := range saved {
			if s.had {
				os.Setenv(s.key, s.val)
			} else {
				os.Unsetenv(s.key)
			}
		}
	})
}

func TestEnabled(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	unset(t, "FLASHCLI_USE_MIRROR", "FLASHCLI_NO_MIRROR")
	reset()
	if Enabled() {
		t.Fatal("no mirror.env and no flags → off")
	}
	t.Setenv("FLASHCLI_USE_MIRROR", "1")
	if !Enabled() {
		t.Fatal("FLASHCLI_USE_MIRROR=1 → on")
	}
	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	if Enabled() {
		t.Fatal("FLASHCLI_NO_MIRROR=1 overrides")
	}
	unset(t, "FLASHCLI_USE_MIRROR", "FLASHCLI_NO_MIRROR")
	os.WriteFile(home+"/mirror.env", []byte("FLASHCLI_USE_MIRROR=1\n"), 0o644)
	if !Enabled() {
		t.Fatal("mirror.env present → on")
	}
}

func TestApplyDefaults(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	t.Setenv("FLASHCLI_USE_MIRROR", "1")
	unset(t, "FLASHCLI_NO_MIRROR", "PIP_INDEX_URL", "PIP_TRUSTED_HOST", "HF_ENDPOINT", "FLASHCLI_PREFER_HF_MIRROR", "FLASHCLI_GIT_PROXY")
	reset()
	Apply()
	if os.Getenv("PIP_INDEX_URL") != DefaultPipIndexURL {
		t.Fatalf("PIP_INDEX_URL=%q", os.Getenv("PIP_INDEX_URL"))
	}
	if os.Getenv("HF_ENDPOINT") != DefaultHFEndpoint {
		t.Fatalf("HF_ENDPOINT=%q", os.Getenv("HF_ENDPOINT"))
	}
	if os.Getenv("FLASHCLI_PREFER_HF_MIRROR") != "1" {
		t.Fatal("FLASHCLI_PREFER_HF_MIRROR not set")
	}
	if os.Getenv("FLASHCLI_GIT_PROXY") != DefaultGitProxyPrefix {
		t.Fatalf("FLASHCLI_GIT_PROXY=%q", os.Getenv("FLASHCLI_GIT_PROXY"))
	}
}

func TestTorchIndexURL(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	unset(t, "FLASHCLI_NO_MIRROR")
	t.Setenv("FLASHCLI_USE_MIRROR", "1")
	reset()
	if got := TorchIndexURL("cu128"); got != TorchIndexBase+"/cu128/" {
		t.Fatalf("mirror torch = %q", got)
	}
	t.Setenv("FLASHCLI_USE_MIRROR", "")
	t.Setenv("FLASHCLI_NO_MIRROR", "1")
	reset()
	if got := TorchIndexURL("cu128"); got != OfficialTorchBase+"/cu128" {
		t.Fatalf("official torch = %q", got)
	}
}

func TestPipExtraArgs(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	unset(t, "FLASHCLI_NO_MIRROR")
	t.Setenv("FLASHCLI_USE_MIRROR", "1")
	t.Setenv("PIP_INDEX_URL", "https://mirror/simple/")
	t.Setenv("PIP_TRUSTED_HOST", "mirror")
	reset()
	got := PipExtraArgs()
	want := []string{"--index-url", "https://mirror/simple/", "--trusted-host", "mirror"}
	if len(got) != 4 || got[0] != want[0] || got[1] != want[1] || got[2] != want[2] || got[3] != want[3] {
		t.Fatalf("PipExtraArgs = %v", got)
	}
}
