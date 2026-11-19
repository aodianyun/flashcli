package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
)

// Apps that were ready with live models are restarted on daemon start; an app
// installed with start=false (ready but no pid/endpoint) is left alone.
func TestRestoreOnStartStartsReadyApps(t *testing.T) {
	home := t.TempDir()
	registry := apps.NewRegistry(home)
	key := "xym/demo:1.0.0"
	preparedKey := "xym/prepared:1.0.0"
	if err := registry.Update(func(m map[string]apps.AppState) error {
		m[key] = apps.AppState{
			Key: key, Version: "1.0.0", State: apps.StateReady,
			Models: []apps.ModelState{{
				Ref: "a/one:1", ID: "one", PID: 123, Endpoint: "http://127.0.0.1:1",
			}},
		}
		m[preparedKey] = apps.AppState{
			Key: preparedKey, Version: "1.0.0", State: apps.StateReady,
			Models: []apps.ModelState{{Ref: "a/one:2", ID: "two", Prepared: true}},
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	launcher := &fakeLauncher{}
	svc := &apps.Service{
		Home:         home,
		Out:          io.Discard,
		Registry:     registry,
		Launcher:     launcher,
		Now:          func() time.Time { return time.Unix(0, 0) },
		StartTimeout: 2 * time.Second,
		Stopper:      func(context.Context, string) (bool, error) { return false, nil },
		Claim:        func(context.Context, string) error { return nil },
	}
	s := &Server{
		Manager:    NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{Inspect: fakeInspect}),
		AppService: func() *apps.Service { return svc },
	}
	s.restoreOnStart(context.Background())

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		st, ok, _ := registry.Get(key)
		if ok && st.State == apps.StateReady {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	st, _, err := registry.Get(key)
	if err != nil {
		t.Fatal(err)
	}
	if st.State != apps.StateReady {
		t.Fatalf("state = %q, want ready", st.State)
	}
	if st.Models[0].PID == 0 || st.Models[0].Endpoint == "" {
		t.Fatalf("model not restarted: %+v", st.Models[0])
	}
	if len(launcher.procs) != 1 {
		t.Fatalf("started %d models, want 1", len(launcher.procs))
	}
	prepared, _, _ := registry.Get(preparedKey)
	if prepared.State != apps.StateReady || len(prepared.Models) != 1 || prepared.Models[0].PID != 0 {
		t.Fatalf("prepared-only app was started: %+v", prepared)
	}
	if len(launcher.procs) != 1 {
		t.Fatalf("prepared-only app started a second model (%d)", len(launcher.procs))
	}
}

// A daemon restart can interrupt a start/install/stop. The next start must not
// leave the app stuck in a transitional state: a start is retried, an install
// is surfaced as failed, and a stop is completed.
func TestRestoreNormalizesInterruptedTransitions(t *testing.T) {
	home := t.TempDir()
	registry := apps.NewRegistry(home)
	startKey := "xym/start:1.0.0"
	installKey := "xym/install:1.0.0"
	stopKey := "xym/stop:1.0.0"
	if err := registry.Update(func(m map[string]apps.AppState) error {
		m[startKey] = apps.AppState{
			Key: startKey, Version: "1.0.0", State: apps.StateStarting,
			Models: []apps.ModelState{{Ref: "a/one:1", ID: "one", Prepared: true}},
		}
		m[installKey] = apps.AppState{
			Key: installKey, Version: "1.0.0", State: apps.StateInstalling,
			Models: []apps.ModelState{{Ref: "a/two:1", ID: "two"}},
		}
		m[stopKey] = apps.AppState{
			Key: stopKey, Version: "1.0.0", State: apps.StateStopping,
			Models: []apps.ModelState{{Ref: "a/three:1", ID: "three", PID: 99, Endpoint: "http://127.0.0.1:1", Prepared: true}},
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	launcher := &fakeLauncher{}
	svc := &apps.Service{
		Home:         home,
		Out:          io.Discard,
		Registry:     registry,
		Launcher:     launcher,
		Now:          func() time.Time { return time.Unix(0, 0) },
		StartTimeout: 2 * time.Second,
		Stopper:      func(context.Context, string) (bool, error) { return false, nil },
		Claim:        func(context.Context, string) error { return nil },
	}
	s := &Server{
		Manager:    NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{Inspect: fakeInspect}),
		AppService: func() *apps.Service { return svc },
	}
	s.restoreOnStart(context.Background())

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		st, _, _ := registry.Get(startKey)
		if st.State == apps.StateReady {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	st, _, _ := registry.Get(startKey)
	if st.State != apps.StateReady || st.Models[0].PID == 0 {
		t.Fatalf("interrupted start not retried: %+v", st)
	}
	if len(launcher.procs) != 1 {
		t.Fatalf("started %d models, want 1", len(launcher.procs))
	}
	installed, _, _ := registry.Get(installKey)
	if installed.State != apps.StateFailed || installed.Error == "" {
		t.Fatalf("interrupted install = %+v", installed)
	}
	stopped, _, _ := registry.Get(stopKey)
	if stopped.State != apps.StateStopped || stopped.Models[0].PID != 0 || stopped.Models[0].Endpoint != "" {
		t.Fatalf("interrupted stop = %+v", stopped)
	}
	if len(launcher.procs) != 1 {
		t.Fatalf("interrupted install/stop started a model (%d)", len(launcher.procs))
	}
}

// A daemon restart restores the app with a new connection; the setup scripts
// the user confirmed before the restart must run again automatically.
func TestRestoreReplaysSavedSetupScripts(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		if _, err := exec.LookPath("python"); err != nil {
			t.Skip("no python interpreter")
		}
	}
	body := []byte("import os\nopen(os.path.join(os.environ['HOME'], 'restored.txt'), 'w').write('ok')\n")
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(body)
	}))
	defer srv.Close()
	previous := http.DefaultTransport
	http.DefaultTransport = srv.Client().Transport
	defer func() { http.DefaultTransport = previous }()
	sum := sha256.Sum256(body)

	home := t.TempDir()
	clientHome := t.TempDir()
	registry := apps.NewRegistry(home)
	key := "xym/demo:1.0.0"
	if err := registry.Update(func(m map[string]apps.AppState) error {
		m[key] = apps.AppState{
			Key: key, Version: "1.0.0", State: apps.StateReady,
			Models: []apps.ModelState{{
				Ref: "a/one:1", ID: "one", PID: 123, Endpoint: "http://127.0.0.1:1", Prepared: true,
			}},
			SetupScripts: []string{"conf"},
			SetupPlan: []apps.SetupScript{{
				Key: "conf", Kind: "python", URL: srv.URL,
				SHA256: hex.EncodeToString(sum[:]),
			}},
			SetupClientHome: clientHome,
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	launcher := &fakeLauncher{}
	svc := &apps.Service{
		Home:         home,
		Out:          io.Discard,
		Registry:     registry,
		Launcher:     launcher,
		Now:          func() time.Time { return time.Unix(0, 0) },
		StartTimeout: 2 * time.Second,
		Stopper:      func(context.Context, string) (bool, error) { return false, nil },
		Claim:        func(context.Context, string) error { return nil },
		Fetch: func(context.Context, flashhub.AppRef) ([]byte, error) {
			return nil, fmt.Errorf("offline: manifest fetch must not be needed on restore")
		},
	}
	s := &Server{
		Manager:    NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{Inspect: fakeInspect}),
		AppService: func() *apps.Service { return svc },
	}
	s.restoreOnStart(context.Background())

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		st, ok, _ := registry.Get(key)
		if ok && st.State == apps.StateReady && st.Connection.BaseURL != "" {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	st, _, _ := registry.Get(key)
	t.Logf("state=%q base=%q scripts=%v home=%q err=%q procs=%d", st.State, st.Connection.BaseURL, st.SetupScripts, st.SetupClientHome, st.SetupError, len(launcher.procs))
	file := filepath.Join(clientHome, "restored.txt")
	deadline = time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(file); err == nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if _, err := os.Stat(file); err != nil {
		t.Fatalf("restore did not replay the saved setup scripts: %v", err)
	}
	// The script writes its output before StartWithSetup returns and stores
	// last_log; wait for the final state instead of racing that save.
	deadline = time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		st, _, _ = registry.Get(key)
		if strings.Contains(strings.Join(st.LastLog, "\n"), "setup conf") {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if st.SetupError != "" {
		t.Fatalf("setup_error = %q", st.SetupError)
	}
	if len(st.SetupScripts) != 1 || st.SetupScripts[0] != "conf" {
		t.Fatalf("setup_scripts = %#v", st.SetupScripts)
	}
	log := strings.Join(st.LastLog, "\n")
	if !strings.Contains(log, "setup conf") {
		t.Fatalf("restored app log = %q", log)
	}
}
