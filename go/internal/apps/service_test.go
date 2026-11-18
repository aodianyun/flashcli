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
	"github.com/aodianyun/flashcli/go/internal/modelrun"
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

type fakeProc struct {
	ref      string
	endpoint string
	pid      int
	healthy  bool
	stopped  bool
}

func (p *fakeProc) Ref() string      { return p.ref }
func (p *fakeProc) Endpoint() string { return p.endpoint }
func (p *fakeProc) PID() int         { return p.pid }
func (p *fakeProc) Healthy(context.Context) error {
	if p.healthy {
		return nil
	}
	return fmt.Errorf("unhealthy")
}
func (p *fakeProc) Running() bool              { return !p.stopped }
func (p *fakeProc) LastLog() string            { return "" }
func (p *fakeProc) Stop(context.Context) error { p.stopped = true; return nil }

type fakeLauncher struct {
	procs   []*fakeProc
	failRef string
	nextPID int
	onStart func(string)
}

func (l *fakeLauncher) StartWithOptions(_ context.Context, ref string, opts modelrun.LoadOptions) (modelrun.ServeProcess, error) {
	if l.onStart != nil {
		l.onStart(ref)
	}
	if ref == l.failRef {
		return nil, fmt.Errorf("boom")
	}
	l.nextPID++
	p := &fakeProc{
		ref: ref, endpoint: fmt.Sprintf("http://127.0.0.1:%d", 20000+l.nextPID),
		pid: l.nextPID, healthy: true,
	}
	l.procs = append(l.procs, p)
	return p, nil
}

func newTestService(t *testing.T, raw []byte, launcher *fakeLauncher) (*Service, *[]string) {
	t.Helper()
	home := t.TempDir()
	prepared := &[]string{}
	svc := &Service{
		Home:         home,
		Out:          io.Discard,
		Registry:     NewRegistry(home),
		Launcher:     launcher,
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
	if res.State.State != StateReady || len(res.State.Models) != 2 {
		t.Fatalf("state = %+v", res.State)
	}
	if len(*prepared) != 2 || len(launcher.procs) != 2 {
		t.Fatalf("prepared=%v procs=%d", *prepared, len(launcher.procs))
	}
	for _, m := range res.State.Models {
		if m.PID == 0 || m.Endpoint == "" || !m.Prepared {
			t.Fatalf("model not recorded: %+v", m)
		}
	}
	if !strings.HasPrefix(res.State.Connection.BaseURL, "http://127.0.0.1:") {
		t.Fatalf("connection = %+v", res.State.Connection)
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
	if res.State.State != StateReady {
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

func TestStartFailureRollsBack(t *testing.T) {
	launcher := &fakeLauncher{failRef: "a/two:1"}
	svc, _ := newTestService(t, manifestJSON("a/one:1", "a/two:1"), launcher)
	_, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true})
	if err == nil {
		t.Fatal("expected start failure")
	}
	if len(launcher.procs) != 1 || !launcher.procs[0].stopped {
		t.Fatalf("first model not rolled back: %+v", launcher.procs)
	}
	st, _, _ := svc.Registry.Get("xym/demo:1.0.0")
	if st.State != StateFailed {
		t.Fatalf("state = %s", st.State)
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
	if len(*prepared) != 1 || len(launcher.procs) != 1 {
		t.Fatalf("prepared=%v procs=%d", *prepared, len(launcher.procs))
	}
}

func TestStopAndUninstall(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	st, err := svc.Stop(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if st.State != StateStopped || st.Models[0].PID != 0 {
		t.Fatalf("stop state = %+v", st)
	}
	if _, err := svc.Uninstall(context.Background(), "xym/demo:1.0.0", false); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := svc.Registry.Get("xym/demo:1.0.0"); ok {
		t.Fatal("app still registered")
	}
}

func TestStopUsesStopperWhenProcIsUnknown(t *testing.T) {
	// The daemon builds a service per request, so a later Stop has no entry in
	// procs. A Manager-backed Stopper must unload the model instead of killing
	// a PID behind the shared Manager's back.
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	stopped := ""
	fresh := &Service{
		Home:         svc.Home,
		Out:          io.Discard,
		Registry:     svc.Registry,
		Launcher:     &fakeLauncher{},
		Now:          func() time.Time { return time.Unix(0, 0) },
		StartTimeout: 2 * time.Second,
		Stopper: func(_ context.Context, ref string) (bool, error) {
			stopped = ref
			return true, nil
		},
	}
	st, err := fresh.Stop(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if stopped != "a/one:1" {
		t.Fatalf("stopper ref = %q", stopped)
	}
	if st.Models[0].PID != 0 || st.Models[0].Endpoint != "" {
		t.Fatalf("model still running: %+v", st.Models[0])
	}
}

// A daemon restart (or a crash/manual kill) leaves state=ready with a dead
// endpoint. Status must not keep advertising 运行中, otherwise 启动 is disabled
// and the connection URL points at nothing.
func TestStatusDowngradesReadyWhenModelsAreGone(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	st, err := svc.Status(context.Background(), "xym/demo:1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	if st.State != StateStopped {
		t.Fatalf("state = %q, want %q", st.State, StateStopped)
	}
	if st.Models[0].PID != 0 || st.Models[0].Endpoint != "" || st.Models[0].Prepared {
		t.Fatalf("stale model kept: %+v", st.Models[0])
	}
	if st.Connection.BaseURL != "" {
		t.Fatalf("stale connection kept: %+v", st.Connection)
	}
}

// A start/stop that is still within its timeout must not be repaired to failed
// by a status query (the UI polls it while the operation runs).
func TestStatusKeepsFreshTransitionalState(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true, NoStart: true}); err != nil {
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

// Start/stop jobs stream these lines into the desktop log.
func TestStartAndStopReportProgress(t *testing.T) {
	svc, _ := newTestService(t, manifestJSON("a/one:1"), &fakeLauncher{})
	var buf strings.Builder
	svc.Out = &buf
	if _, err := svc.Install(context.Background(), "xym/demo", InstallOptions{Yes: true}); err != nil {
		t.Fatal(err)
	}
	buf.Reset()
	if _, err := svc.Stop(context.Background(), "xym/demo:1.0.0"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buf.String(), "stopping a/one:1") {
		t.Fatalf("stop log = %q", buf.String())
	}
	buf.Reset()
	if _, err := svc.Start(context.Background(), "xym/demo:1.0.0", false); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	if !strings.Contains(out, "starting a/one:1") || !strings.Contains(out, "waiting for a/one:1") {
		t.Fatalf("start log = %q", out)
	}
}
