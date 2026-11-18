package apps

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

const setupScriptBody = `import json, os, sys
out = {"args": sys.argv[1:], "home": os.environ.get("HOME")}
with open(os.path.join(os.environ["HOME"], "setup.json"), "w", encoding="utf-8") as f:
    json.dump(out, f)
`

func TestRunSetupScriptUsesExplicitArgs(t *testing.T) {
	if _, err := setupPython(); err != nil {
		t.Skip(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(setupScriptBody))
	}))
	defer srv.Close()
	sum := sha256.Sum256([]byte(setupScriptBody))
	home := t.TempDir()
	svc := &Service{Out: os.Stdout}
	conn := Connection{
		BaseURL: "http://127.0.0.1:4567/v1",
		APIKey:  "local",
		Models:  []string{"gemma4_e2b_it"},
	}
	script := SetupScript{
		Key: "workbuddy", Kind: "python", URL: srv.URL,
		SHA256: hex.EncodeToString(sum[:]),
		Args:   []string{"{base_url}", "{model}", "--api-key {api_key}"},
	}
	if err := svc.runSetupScript(context.Background(), script, conn, home); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(filepath.Join(home, "setup.json"))
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Args []string `json:"args"`
		Home string   `json:"home"`
	}
	if err := json.Unmarshal(blob, &got); err != nil {
		t.Fatal(err)
	}
	want := []string{"http://127.0.0.1:4567/v1", "gemma4_e2b_it", "--api-key", "local"}
	if strings.Join(got.Args, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("args = %#v, want %#v", got.Args, want)
	}
	if got.Home != home {
		t.Fatalf("HOME = %q, want %q", got.Home, home)
	}
}

func TestRunSetupScriptRejectsHashMismatch(t *testing.T) {
	if _, err := setupPython(); err != nil {
		t.Skip(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(setupScriptBody))
	}))
	defer srv.Close()
	home := t.TempDir()
	svc := &Service{Out: os.Stdout}
	conn := Connection{BaseURL: "http://127.0.0.1:4567/v1", APIKey: "local", Models: []string{"m"}}
	script := SetupScript{
		Key: "x", Kind: "python", URL: srv.URL,
		SHA256: strings.Repeat("0", 64), Args: []string{"{base_url}", "{model}"},
	}
	err := svc.runSetupScript(context.Background(), script, conn, home)
	if err == nil || !strings.Contains(err.Error(), "sha256 mismatch") {
		t.Fatalf("error = %v", err)
	}
	if _, statErr := os.Stat(filepath.Join(home, "setup.json")); !os.IsNotExist(statErr) {
		t.Fatal("script ran despite a hash mismatch")
	}
}

func TestStartRunsConfirmedSetupScripts(t *testing.T) {
	if _, err := setupPython(); err != nil {
		t.Skip(err)
	}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(setupScriptBody))
	}))
	defer srv.Close()
	previous := http.DefaultTransport
	http.DefaultTransport = srv.Client().Transport
	defer func() { http.DefaultTransport = previous }()
	sum := sha256.Sum256([]byte(setupScriptBody))
	scriptJSON := fmt.Sprintf(`{
      "key": "workbuddy",
      "kind": "python",
      "url": %q,
      "sha256": %q,
      "args": ["{base_url}", "{model}", "--api-key {api_key}"]
    }`, srv.URL, hex.EncodeToString(sum[:]))
	svc, _ := newTestService(t, []byte(setupManifest(scriptJSON)), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/workbuddy", InstallOptions{
		Yes: true, NoStart: true, OS: "windows", Arch: "x86_64",
	}); err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	if _, err := svc.StartWithSetup(context.Background(), "xym/workbuddy:1.0.0", false, SetupOptions{
		Scripts:    []string{"workbuddy"},
		ClientHome: home,
	}); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(filepath.Join(home, "setup.json"))
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Args []string `json:"args"`
		Home string   `json:"home"`
	}
	if err := json.Unmarshal(blob, &got); err != nil {
		t.Fatal(err)
	}
	if len(got.Args) != 4 || got.Args[0] == "" || got.Args[1] == "" || got.Args[2] != "--api-key" || got.Args[3] != "local" {
		t.Fatalf("args = %#v", got.Args)
	}
	if got.Home != home {
		t.Fatalf("HOME = %q, want %q", got.Home, home)
	}
}

func TestSetupEnvMapsWindowsHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("windows path is used as-is there")
	}
	env := setupEnv(`C:\Users\Demo`)
	found := ""
	for _, item := range env {
		if strings.HasPrefix(item, "HOME=") {
			found = strings.TrimPrefix(item, "HOME=")
		}
	}
	if found != "/mnt/c/Users/Demo" {
		t.Fatalf("HOME = %q", found)
	}
}
