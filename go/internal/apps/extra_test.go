package apps

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestManifestValidationErrors(t *testing.T) {
	base := func() *Manifest {
		m := &Manifest{Format: "flashcli-application", AppFormatVersion: 1, ProtocolVersion: 1, Name: "x", Version: "1"}
		m.Supported.OS = []string{"linux"}
		m.Supported.Arch = []string{"x86_64"}
		m.Install.Commands = map[string]string{"linux": "echo hi"}
		m.Model.Bundles = []Bundle{{Bundle: "a/b:1"}}
		return m
	}
	if errs := Validate(base()); len(errs) > 0 {
		t.Fatalf("valid manifest rejected: %v", errs)
	}
	cases := map[string]func(*Manifest){
		"format":     func(m *Manifest) { m.Format = "x" },
		"version":    func(m *Manifest) { m.AppFormatVersion = 2 },
		"name":       func(m *Manifest) { m.Name = "" },
		"release":    func(m *Manifest) { m.Version = " " },
		"os":         func(m *Manifest) { m.Supported.OS = nil },
		"arch":       func(m *Manifest) { m.Supported.Arch = nil },
		"commands":   func(m *Manifest) { m.Install.Commands = nil },
		"bundles":    func(m *Manifest) { m.Model.Bundles = nil },
		"bundle ref": func(m *Manifest) { m.Model.Bundles = []Bundle{{Bundle: ""}} },
	}
	for name, mutate := range cases {
		m := base()
		mutate(m)
		if errs := Validate(m); len(errs) == 0 {
			t.Fatalf("%s: expected validation error", name)
		}
	}
}

func TestInstallPreparesThenStartsInOrder(t *testing.T) {
	var mu sync.Mutex
	var events []string
	launcher := &fakeLauncher{onStart: func(ref string) {
		mu.Lock()
		events = append(events, "start:"+ref)
		mu.Unlock()
	}}
	svc, _ := newTestService(t, manifestJSON("a/one:1", "a/two:1"), launcher)
	svc.Prepare = func(_ context.Context, ref string) error {
		mu.Lock()
		events = append(events, "prepare:"+ref)
		mu.Unlock()
		return nil
	}
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	want := []string{"prepare:a/one:1", "prepare:a/two:1", "start:a/one:1", "start:a/two:1"}
	if len(events) != len(want) {
		t.Fatalf("events = %v", events)
	}
	for i := range want {
		if events[i] != want[i] {
			t.Fatalf("events = %v, want %v", events, want)
		}
	}
}

func TestInstallForceRestarts(t *testing.T) {
	launcher := &fakeLauncher{}
	svc, prepared := newTestService(t, manifestJSON("a/one:1"), launcher)
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true, Force: true}); err != nil {
		t.Fatal(err)
	}
	if len(launcher.procs) != 2 {
		t.Fatalf("force did not restart the model (procs=%d)", len(launcher.procs))
	}
	if len(*prepared) != 1 {
		t.Fatalf("already prepared bundle was pulled again: %v", *prepared)
	}
}

func TestRegistryConcurrentUpdates(t *testing.T) {
	home := t.TempDir()
	reg := NewRegistry(home)
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			for j := 0; j < 5; j++ {
				key := string(rune('a'+i)) + "/x:1"
				if err := reg.Update(func(m map[string]AppState) error {
					m[key] = AppState{Key: key, State: StateReady}
					return nil
				}); err != nil {
					errs <- err
					return
				}
			}
		}(i)
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatalf("concurrent update failed: %v", err)
	}
	apps, err := reg.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(apps) != 8 {
		t.Fatalf("lost updates: %d entries", len(apps))
	}
}

func TestInstallUsesClientPlatformAndHandlesScript(t *testing.T) {
	marker := filepath.Join(t.TempDir(), "script-ran")
	svc, _ := newTestService(t, manifestJSONFor("windows", "touch "+marker, "a/one:1"), &fakeLauncher{})
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		OS:            "windows",
		Arch:          "x86_64",
		ScriptHandled: true,
		NoStart:       true,
	})
	if err != nil {
		t.Fatalf("windows app on a linux host: %v", err)
	}
	if !res.InstallRan || !res.State.Install.Executed {
		t.Fatalf("script decision not recorded: %+v", res.State.Install)
	}
	if res.State.Install.Command != "touch "+marker {
		t.Fatalf("recorded command = %q", res.State.Install.Command)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Fatal("daemon executed a command marked as handled by the client")
	}
}

func TestInstallRejectsUnsupportedClientPlatform(t *testing.T) {
	svc, _ := newTestService(t, manifestJSONFor("windows", "echo x", "a/one:1"), &fakeLauncher{})
	_, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		OS:            "linux",
		Arch:          "x86_64",
		ScriptHandled: true,
	})
	if err == nil || !strings.Contains(err.Error(), "does not support linux/x86_64") {
		t.Fatalf("err = %v", err)
	}
}

func TestInstallConfirmsThenRuns(t *testing.T) {
	launcher := &fakeLauncher{}
	svc, _ := newTestService(t, manifestJSON("a/one:1"), launcher)
	asked := 0
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		Confirm: func(string) bool { asked++; return true },
	})
	if err != nil {
		t.Fatal(err)
	}
	if asked != 1 || !res.InstallRan || !res.State.Install.Executed {
		t.Fatalf("confirm did not run the command: asked=%d res=%+v", asked, res)
	}
}

func TestInstallDeclinedSkipsScript(t *testing.T) {
	launcher := &fakeLauncher{}
	svc, _ := newTestService(t, manifestJSON("a/one:1"), launcher)
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{
		Confirm: func(string) bool { return false },
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.InstallRan || !res.InstallSkipped || !res.State.Install.Skipped {
		t.Fatalf("declined install = %+v", res)
	}
}
