package apps

import (
	"context"
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
)

func manifestJSON(bundles ...string) []byte {
	return manifestJSONFor(runtime.GOOS, "echo install-ok", bundles...)
}

// manifestJSONFor builds a manifest for an explicit platform, used to test the
// desktop client's platform (Windows) on a Linux test host.
func manifestJSONFor(goos, command string, bundles ...string) []byte {
	items := make([]string, 0, len(bundles))
	for _, b := range bundles {
		items = append(items, fmt.Sprintf(`{"bundle":%q,"default":true,"serve":{"options":{}}}`, b))
	}
	return []byte(fmt.Sprintf(`{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "demo",
  "version": "1.0.0",
  "display_name": "Demo",
  "supported": {"os": [%q], "arch": ["x86_64", "arm64"]},
  "install": {"commands": {%q: %q}},
  "model": {"bundles": [%s]},
  "config": []
}`, goos, goos, command, strings.Join(items, ",")))
}

// fakeProc/fakeLauncher keep the old test helpers for assertions that an
// install/activate never starts a model. The service no longer owns processes.
type fakeProc struct{}

type fakeLauncher struct {
	procs   []*fakeProc
	onStart func(string)
}

func newTestService(t *testing.T, raw []byte, _ *fakeLauncher) (*Service, *[]string) {
	t.Helper()
	home := t.TempDir()
	prepared := &[]string{}
	svc := &Service{
		Home:         home,
		Out:          io.Discard,
		Registry:     NewRegistry(home),
		Now:          func() time.Time { return time.Unix(0, 0) },
		StartTimeout: 2 * time.Second,
		Fetch: func(context.Context, flashhub.AppRef) ([]byte, error) {
			return raw, nil
		},
		Prepare: func(_ context.Context, ref string) error {
			*prepared = append(*prepared, ref)
			return nil
		},
	}
	return svc, prepared
}

func TestInstallHappyPath(t *testing.T) {
	launcher := &fakeLauncher{}
	svc, prepared := newTestService(t, manifestJSON("a/one:1", "a/two:1"), launcher)
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true})
	if err != nil {
		t.Fatal(err)
	}
	if !res.InstallRan {
		t.Fatal("install command did not run")
	}
	if res.State.State != StatePrepared || len(res.State.Models) != 2 {
		t.Fatalf("state = %+v", res.State)
	}
	if len(*prepared) != 2 || len(launcher.procs) != 0 {
		t.Fatalf("prepared=%v procs=%d", *prepared, len(launcher.procs))
	}
	for _, m := range res.State.Models {
		if m.PID != 0 || m.Endpoint != "" || !m.Prepared {
			t.Fatalf("model not recorded as prepared-only: %+v", m)
		}
	}
	if res.State.Connection.BaseURL != "http://127.0.0.1:8790/v1" {
		t.Fatalf("install did not advertise the gateway: %+v", res.State.Connection)
	}
	if _, err := os.Stat(svc.Registry.Path); err != nil {
		t.Fatalf("registry not written: %v", err)
	}
}

func TestInstallSkipsScriptWithoutConfirmation(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if res.InstallRan || !res.InstallSkipped || !res.State.Install.Skipped {
		t.Fatalf("install = %+v skipped=%v", res, res.State.Install.Skipped)
	}
	if res.State.State != StatePrepared {
		t.Fatalf("state = %s", res.State.State)
	}
}

func TestInstallScriptFailureAborts(t *testing.T) {
	raw := []byte(strings.Replace(string(manifestJSON("a/one:1")), "echo install-ok", "exit 3", 1))
	launcher := &fakeLauncher{}
	svc, prepared := newTestService(t, raw, launcher)
	_, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true})
	if err == nil {
		t.Fatal("expected failure")
	}
	if len(*prepared) != 0 || len(launcher.procs) != 0 {
		t.Fatalf("prepared=%v procs=%d", *prepared, len(launcher.procs))
	}
	st, ok, _ := svc.Registry.Get("xym/demo:1.0.0")
	if !ok || st.State != StateFailed {
		t.Fatalf("state = %+v ok=%v", st, ok)
	}
}

func TestReinstallIsIdempotent(t *testing.T) {
	launcher := &fakeLauncher{}
	svc, prepared := newTestService(t, manifestJSON("a/one:1"), launcher)
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	res, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true})
	if err != nil {
		t.Fatal(err)
	}
	if !res.AlreadyReady {
		t.Fatal("second install was not reported as ready")
	}
	if len(*prepared) != 1 || len(launcher.procs) != 0 {
		t.Fatalf("prepared=%v procs=%d", *prepared, len(launcher.procs))
	}
}

func TestActivateDeactivateUninstall(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	st, err := svc.Activate(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if st.State != StateReady {
		t.Fatalf("activate state = %+v", st)
	}
	if st.Connection.BaseURL != "http://127.0.0.1:8790/v1" {
		t.Fatalf("gateway connection = %+v", st.Connection)
	}
	if st.Models[0].PID != 0 || st.Models[0].Endpoint != "" {
		t.Fatalf("activation recorded a process: %+v", st.Models[0])
	}

	st, err = svc.Deactivate(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if st.State != StateStopped {
		t.Fatalf("deactivate state = %+v", st)
	}

	if _, err := svc.Uninstall(context.Background(), "xym/demo:1.0.0", false); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := svc.Registry.Get("xym/demo:1.0.0"); ok {
		t.Fatal("app still registered")
	}
}

func TestStatusKeepsFreshTransitionalState(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	st, ok, err := svc.Registry.Get("xym/demo:1.0.0")
	if err != nil || !ok {
		t.Fatalf("get: ok=%v err=%v", ok, err)
	}
	st.State = StateStarting
	st.UpdatedAt = svc.now().UTC().Format(time.RFC3339)
	svc.save(&st)
	got, err := svc.Status(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if got.State != StateStarting {
		t.Fatalf("state = %q, want %q", got.State, StateStarting)
	}
}
