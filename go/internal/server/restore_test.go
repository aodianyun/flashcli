package server

import (
	"context"
	"io"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/apps"
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
