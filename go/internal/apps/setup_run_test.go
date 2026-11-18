package apps

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
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
	started, err := svc.StartWithSetup(context.Background(), "xym/workbuddy:1.0.0", false, SetupOptions{
		Scripts:    []string{"workbuddy"},
		ClientHome: home,
		Provided:   true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(started.SetupScripts) != 1 || started.SetupScripts[0] != "workbuddy" {
		t.Fatalf("setup_scripts = %#v", started.SetupScripts)
	}
	if started.SetupClientHome != home {
		t.Fatalf("setup_client_home = %q, want %q", started.SetupClientHome, home)
	}
	saved, _, _ := svc.Registry.Get("xym/workbuddy:1.0.0")
	log := strings.Join(saved.LastLog, "\n")
	if !strings.Contains(log, "setup workbuddy: done") {
		t.Fatalf("last_log = %q", log)
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

const appendScriptBody = `import os, sys
with open(os.path.join(os.environ["HOME"], "order.txt"), "a", encoding="utf-8") as f:
    f.write(sys.argv[1] + "\n")
`

const failScriptBody = `import sys
sys.exit(3)
`

func TestSetupScriptsRunInOrderAndStopOnFailure(t *testing.T) {
	if _, err := setupPython(); err != nil {
		t.Skip(err)
	}
	one := []byte(appendScriptBody)
	two := []byte(appendScriptBody)
	fail := []byte(failScriptBody)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/one":
			_, _ = w.Write(one)
		case "/two":
			_, _ = w.Write(two)
		case "/fail":
			_, _ = w.Write(fail)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	hash := func(blob []byte) string {
		sum := sha256.Sum256(blob)
		return hex.EncodeToString(sum[:])
	}
	m := &Manifest{}
	m.Setup.Scripts = []SetupScript{
		{Key: "one", Kind: "python", URL: srv.URL + "/one", SHA256: hash(one), Args: []string{"one"}},
		{Key: "two", Kind: "python", URL: srv.URL + "/two", SHA256: hash(two), Args: []string{"two"}},
	}
	conn := Connection{BaseURL: "http://127.0.0.1:1/v1", APIKey: "local", Models: []string{"m"}}
	svc := &Service{Out: io.Discard}
	home := t.TempDir()
	st := &AppState{Connection: conn}
	svc.runSetupScripts(context.Background(), m.Setup.Scripts, st, home)
	blob, err := os.ReadFile(filepath.Join(home, "order.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(blob) != "one\ntwo\n" {
		t.Fatalf("order = %q", blob)
	}

	// A failing first script stops the second.
	home2 := t.TempDir()
	m.Setup.Scripts = []SetupScript{
		{Key: "fail", Kind: "python", URL: srv.URL + "/fail", SHA256: hash(fail)},
		{Key: "two", Kind: "python", URL: srv.URL + "/two", SHA256: hash(two), Args: []string{"two"}},
	}
	svc.runSetupScripts(context.Background(), m.Setup.Scripts, &AppState{Connection: conn}, home2)
	if _, err := os.Stat(filepath.Join(home2, "order.txt")); !os.IsNotExist(err) {
		t.Fatal("a script ran after the first failure")
	}
}

func TestInstallRunsConfirmedSetupScripts(t *testing.T) {
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
	home := t.TempDir()
	res, err := svc.Install(context.Background(), "xym/workbuddy", InstallOptions{
		Yes: true, OS: "windows", Arch: "x86_64",
		SetupScripts: []string{"workbuddy"}, ClientHome: home, SetupProvided: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(home, "setup.json")); err != nil {
		t.Fatalf("setup script did not run during install: %v", err)
	}
	if len(res.State.SetupScripts) != 1 || res.State.SetupScripts[0] != "workbuddy" {
		t.Fatalf("setup_scripts = %#v", res.State.SetupScripts)
	}
	if res.State.SetupClientHome != home {
		t.Fatalf("setup_client_home = %q, want %q", res.State.SetupClientHome, home)
	}
	if len(res.State.SetupPlan) != 1 || res.State.SetupPlan[0].URL != srv.URL {
		t.Fatalf("setup_plan = %#v", res.State.SetupPlan)
	}
}

// A daemon restart restores the app with a new connection; Start (no explicit
// selection) must replay the scripts the user confirmed on the previous start.
func TestRestoreReplaysSavedSetupScripts(t *testing.T) {
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
	// Persisted by the previous start: the confirmed selection and its pinned
	// definition. No manifest fetch is available on restore.
	if err := svc.Registry.Update(func(m map[string]AppState) error {
		st, ok := m["xym/workbuddy:1.0.0"]
		if !ok {
			t.Fatal("app not installed")
		}
		st.SetupScripts = []string{"workbuddy"}
		st.SetupPlan = []SetupScript{{
			Key: "workbuddy", Kind: "python", URL: srv.URL,
			SHA256: hex.EncodeToString(sum[:]),
			Args:   []string{"{base_url}", "{model}", "--api-key {api_key}"},
		}}
		st.SetupClientHome = home
		m["xym/workbuddy:1.0.0"] = st
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	svc.Fetch = func(context.Context, flashhub.AppRef) ([]byte, error) {
		return nil, fmt.Errorf("offline: manifest fetch must not be needed on restore")
	}
	started, err := svc.Start(context.Background(), "xym/workbuddy:1.0.0", false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(home, "setup.json")); err != nil {
		t.Fatalf("restore did not replay the saved setup scripts: %v", err)
	}
	if len(started.SetupScripts) != 1 || started.SetupScripts[0] != "workbuddy" {
		t.Fatalf("setup_scripts = %#v", started.SetupScripts)
	}
}

// A start interrupted by shutdown keeps its intent so the next daemon start
// retries it instead of showing "failed: context canceled".
func TestStartCanceledKeepsIntent(t *testing.T) {
	launcher := &fakeLauncher{failRef: "a/one:1"}
	svc, _ := newTestService(t, manifestJSON("a/one:1"), launcher)
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		Yes: true, NoStart: true,
	}); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := svc.Start(ctx, "xym/demo:1.0.0", false); err == nil {
		t.Fatal("expected a start error")
	}
	st, _, _ := svc.Registry.Get("xym/demo:1.0.0")
	if st.State != StateStarting || st.Error != "" {
		t.Fatalf("interrupted start = state %q error %q", st.State, st.Error)
	}
}

func TestSetupFailureIgnoresInterruptedContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if got := setupFailure(ctx, context.Canceled); got != "" {
		t.Fatalf("canceled error persisted: %q", got)
	}
	if got := setupFailure(context.Background(), fmt.Errorf("script failed")); got != "script failed" {
		t.Fatalf("failure = %q", got)
	}
}

// A failure from an earlier run is cleared as soon as the app starts again.
func TestStartClearsStaleSetupError(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		Yes: true, NoStart: true,
	}); err != nil {
		t.Fatal(err)
	}
	if err := svc.Registry.Update(func(m map[string]AppState) error {
		st, ok := m["xym/demo:1.0.0"]
		if !ok {
			t.Fatal("app not installed")
		}
		st.SetupError = "setup skipped: context canceled"
		m["xym/demo:1.0.0"] = st
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Start(context.Background(), "xym/demo:1.0.0", false); err != nil {
		t.Fatal(err)
	}
	st, _, _ := svc.Registry.Get("xym/demo:1.0.0")
	if st.SetupError != "" {
		t.Fatalf("setup_error = %q", st.SetupError)
	}
}

// An explicit empty selection (Provided) clears both the keys and the pinned
// definitions, so a later restore does not run them again.
func TestExplicitEmptySetupSelectionClearsSavedPlan(t *testing.T) {
	scriptJSON := `{
      "key": "conf",
      "kind": "python",
      "url": "https://example.invalid/conf.py",
      "sha256": "` + strings.Repeat("a", 64) + `",
      "args": ["{base_url}"]
    }`
	svc, _ := newTestService(t, []byte(setupManifest(scriptJSON)), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/workbuddy", InstallOptions{
		Yes: true, NoStart: true, OS: "windows", Arch: "x86_64",
	}); err != nil {
		t.Fatal(err)
	}
	if err := svc.Registry.Update(func(m map[string]AppState) error {
		st, ok := m["xym/workbuddy:1.0.0"]
		if !ok {
			t.Fatal("app not installed")
		}
		st.SetupScripts = []string{"conf"}
		st.SetupPlan = []SetupScript{{
			Key: "conf", Kind: "python", URL: "https://example.invalid/conf.py",
			SHA256: strings.Repeat("a", 64),
		}}
		m["xym/workbuddy:1.0.0"] = st
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.StartWithSetup(context.Background(), "xym/workbuddy:1.0.0", false, SetupOptions{
		Provided: true,
	}); err != nil {
		t.Fatal(err)
	}
	st, _, _ := svc.Registry.Get("xym/workbuddy:1.0.0")
	if len(st.SetupScripts) != 0 || len(st.SetupPlan) != 0 {
		t.Fatalf("explicit empty selection kept scripts=%v plan=%v", st.SetupScripts, st.SetupPlan)
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
