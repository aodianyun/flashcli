package apps

import (
	"strings"
	"testing"
)

const sample = `{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "workbuddy",
  "version": "1.0.0",
  "display_name": "WorkBuddy",
  "supported": {"os": ["windows"], "arch": ["x86_64", "arm64"]},
  "install": {"commands": {"windows": "https://example.com/WorkBuddy.exe"}},
  "model": {"bundles": [
    {"bundle": "xym/gemma4_e2b_it:1.0.1", "default": true, "serve": {"options": {}}},
    {"bundle": "xym/spark_x26_4b:1.0.7", "default": false, "serve": {"options": {}}}
  ]},
  "config": []
}`

func TestParseAndValidate(t *testing.T) {
	m, err := Parse([]byte(sample))
	if err != nil {
		t.Fatal(err)
	}
	if m.Name != "workbuddy" || m.Version != "1.0.0" {
		t.Fatalf("manifest = %+v", m)
	}
	if !Supported(m, "windows", "amd64") {
		t.Fatal("windows/amd64 should be supported")
	}
	if Supported(m, "linux", "amd64") {
		t.Fatal("linux should not be supported")
	}
	if _, err := Parse([]byte(`{"format":"other"}`)); err == nil {
		t.Fatal("expected validation error")
	}
	if err := Validate(&Manifest{Format: "flashcli-application", AppFormatVersion: 2}); len(err) == 0 {
		t.Fatal("expected version error")
	}
}

func TestPlatformCommandPrefersArch(t *testing.T) {
	m := &Manifest{}
	m.Install.Commands = map[string]string{
		"darwin":       "curl -fsSL https://x/install.sh | bash",
		"darwin/arm64": "curl -fsSL https://x/install-arm.sh | bash",
		"linux":        "curl -fsSL https://x/install.sh | bash",
	}
	key, cmd, ok := PlatformCommand(m, "darwin", "arm64")
	if !ok || key != "darwin/arm64" || !strings.Contains(cmd, "install-arm") {
		t.Fatalf("got %q %q %v", key, cmd, ok)
	}
	if _, _, ok := PlatformCommand(m, "windows", "amd64"); ok {
		t.Fatal("windows should have no command")
	}
}

func TestDefaultBundles(t *testing.T) {
	m, err := Parse([]byte(sample))
	if err != nil {
		t.Fatal(err)
	}
	if got := DefaultBundles(m, nil); len(got) != 1 || got[0] != "xym/gemma4_e2b_it:1.0.1" {
		t.Fatalf("defaults = %v", got)
	}
	if got := DefaultBundles(m, []string{"a/b:1"}); len(got) != 1 || got[0] != "a/b:1" {
		t.Fatalf("override = %v", got)
	}
	multi := &Manifest{}
	multi.Model.Bundles = []Bundle{{Bundle: "a/one:1", Default: true}, {Bundle: "a/two:1", Default: true}}
	if got := DefaultBundles(multi, nil); len(got) != 2 {
		t.Fatalf("multi = %v", got)
	}
	none := &Manifest{}
	none.Model.Bundles = []Bundle{{Bundle: "a/only:1"}}
	if got := DefaultBundles(none, nil); len(got) != 1 || got[0] != "a/only:1" {
		t.Fatalf("fallback = %v", got)
	}
}

func TestURLShellAndModelName(t *testing.T) {
	if !IsURL("https://example.com/a.exe") || IsURL("curl -fsSL https://x | bash") {
		t.Fatal("URL detection wrong")
	}
	if name, args := ShellInvocation("linux", "echo hi"); name != "/bin/sh" || len(args) != 2 {
		t.Fatalf("linux shell = %s %v", name, args)
	}
	if name, _ := ShellInvocation("windows", "echo hi"); name != "powershell.exe" {
		t.Fatalf("windows shell = %s", name)
	}
	if got := ModelName("xym/gemma4_e2b_it:1.0.1"); got != "gemma4_e2b_it" {
		t.Fatalf("model name = %q", got)
	}
}

func TestRegistryRoundTrip(t *testing.T) {
	home := t.TempDir()
	reg := NewRegistry(home)
	err := reg.Update(func(m map[string]AppState) error {
		m["a/b:1"] = AppState{Key: "a/b:1", Version: "1", State: StateReady}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	st, ok, err := reg.Get("a/b:1")
	if err != nil || !ok || st.State != StateReady {
		t.Fatalf("get = %+v ok=%v err=%v", st, ok, err)
	}
	if _, err := reg.Load(); err != nil {
		t.Fatal(err)
	}
}
