package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

type fakeSource struct{}

func (fakeSource) Models(context.Context) ([]host.Model, error) {
	return []host.Model{{Ref: "demo:1", CacheKey: "demo/1", BundleCached: true}}, nil
}
func (fakeSource) Storage(context.Context) ([]host.Area, error) {
	return []host.Area{{Name: "models", Bytes: 10}}, nil
}

func TestHealthAndModels(t *testing.T) {
	s := &Server{Source: fakeSource{}}
	h := s.Handler()
	for _, tc := range []struct {
		path string
		key  string
	}{
		{"/health", "status"},
		{"/api/v1/models", "models"},
		{"/api/v1/storage", "areas"},
	} {
		req := httptest.NewRequest(http.MethodGet, tc.path, nil)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s: status %d", tc.path, rec.Code)
		}
		var body map[string]any
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		if _, ok := body[tc.key]; !ok {
			t.Fatalf("%s: missing %q in %s", tc.path, tc.key, rec.Body.String())
		}
	}
}

func TestNotImplemented(t *testing.T) {
	s := &Server{Source: fakeSource{}}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/pull", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusNotImplemented {
		t.Fatalf("status = %d", rec.Code)
	}
}

type fakePuller struct{}

func (fakePuller) Pull(ctx context.Context, ref string, opts host.PullOptions) (host.PullResult, error) {
	if opts.Progress != nil {
		opts.Progress(host.PullEvent{Phase: "resolve", Ref: ref})
		opts.Progress(host.PullEvent{Phase: "done", Ref: ref})
	}
	return host.PullResult{BundleRoot: "/tmp/bundle", Checkpoint: "/tmp/weights"}, nil
}

func TestPullJob(t *testing.T) {
	s := &Server{Source: fakeSource{}, Puller: fakePuller{}, Jobs: NewJobManager()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/pull", strings.NewReader(`{"ref":"demo:1"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d: %s", rec.Code, rec.Body.String())
	}
	var accepted map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &accepted); err != nil {
		t.Fatal(err)
	}
	id := accepted["job_id"]
	if id == "" {
		t.Fatal("missing job_id")
	}
	for i := 0; i < 50; i++ {
		j, ok := s.Jobs.Get(id)
		if ok {
			j.mu.Lock()
			state := j.State
			j.mu.Unlock()
			if state == "done" || state == "failed" {
				if state != "done" {
					t.Fatalf("job state=%s", state)
				}
				return
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("job did not finish")
}

type fakeServe struct {
	ref      string
	endpoint string
	stopped  bool
	// healthy blocks Healthy until closed when non-nil (startup in progress).
	healthy chan struct{}
}

func (f *fakeServe) Ref() string      { return f.ref }
func (f *fakeServe) Endpoint() string { return f.endpoint }
func (f *fakeServe) PID() int         { return 1234 }
func (f *fakeServe) Healthy(ctx context.Context) error {
	if f.healthy != nil {
		select {
		case <-f.healthy:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return nil
}
func (f *fakeServe) Running() bool              { return !f.stopped }
func (f *fakeServe) LastLog() string            { return "" }
func (f *fakeServe) Stop(context.Context) error { f.stopped = true; return nil }

type fakeLauncher struct {
	procs []*fakeServe
	err   error
}

func (f *fakeLauncher) Start(_ context.Context, ref string, port int) (ServeProcess, error) {
	if f.err != nil {
		return nil, f.err
	}
	p := &fakeServe{ref: ref, endpoint: fmt.Sprintf("http://127.0.0.1:%d", port)}
	f.procs = append(f.procs, p)
	return p, nil
}

func (f *fakeLauncher) StartWithOptions(ctx context.Context, ref string, opts modelrun.LoadOptions) (ServeProcess, error) {
	return f.Start(ctx, ref, opts.Port)
}

func fakeInspect(string) (BundleInfo, error) { return BundleInfo{}, nil }

func TestLoadRejectsRunOnly(t *testing.T) {
	m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{
		Inspect: func(string) (BundleInfo, error) {
			return BundleInfo{Name: "demo", RunOnly: true}, nil
		},
	})
	_, err := m.Load(context.Background(), "demo:1")
	if err == nil || !strings.Contains(err.Error(), "run-only") {
		t.Fatalf("load error = %v, want run-only", err)
	}
}

func TestLoadUnload(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	info, err := m.Load(context.Background(), "demo:1")
	if err != nil {
		t.Fatal(err)
	}
	if info.State != "ready" || info.Endpoint == "" {
		t.Fatalf("info = %+v", info)
	}
	if len(m.List()) != 1 {
		t.Fatalf("loaded = %d", len(m.List()))
	}
	if err := m.Unload(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if !l.procs[0].stopped {
		t.Fatal("serve process was not stopped")
	}
}

func TestManagerCapacity(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{MaxLoaded: 1, Inspect: fakeInspect})
	if _, err := m.Load(context.Background(), "a:1"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.Load(context.Background(), "b:1"); !errors.Is(err, ErrResourceExhausted) {
		t.Fatalf("second load error = %v", err)
	}
	if err := m.Unload(context.Background(), "a:1"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.Load(context.Background(), "b:1"); err != nil {
		t.Fatal(err)
	}
}

func TestLoadReusesResident(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	a, err := m.Load(context.Background(), "demo:1")
	if err != nil {
		t.Fatal(err)
	}
	b, err := m.Load(context.Background(), "demo:1")
	if err != nil {
		t.Fatal(err)
	}
	if a.Endpoint != b.Endpoint || len(l.procs) != 1 {
		t.Fatalf("unexpected reload: a=%+v b=%+v procs=%d", a, b, len(l.procs))
	}
}

func TestGPUStatus(t *testing.T) {
	s := &Server{Source: fakeSource{}, GPU: func(context.Context) ([]gpu.Device, error) {
		return []gpu.Device{{Index: 0, Name: "GPU", MemoryTotal: 1024}}, nil
	}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/gpu", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "GPU") {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestResourcesAndLoaded(t *testing.T) {
	s := &Server{Source: fakeSource{}, GPU: func(context.Context) ([]gpu.Device, error) {
		return []gpu.Device{{Index: 0, Name: "GPU", MemoryFree: 1024}}, nil
	}, Manager: NewManager(&fakeLauncher{})}
	for _, path := range []string{"/api/v1/resources", "/api/v1/models/loaded", "/api/v1/version"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s: status %d", path, rec.Code)
		}
	}
}

func TestInferEndpointRemoved(t *testing.T) {
	s := &Server{Source: fakeSource{}}
	req := httptest.NewRequest(http.MethodPost, "/v1/infer", strings.NewReader(`{}`))
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound && rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestAuth(t *testing.T) {
	s := &Server{Source: fakeSource{}, Token: "secret"}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d", rec.Code)
	}
	req = httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	req.Header.Set("X-Flashcli-Token", "secret")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("authorized status = %d", rec.Code)
	}
}

func TestVRAMAdmission(t *testing.T) {
	m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{
		GPU: func(context.Context) ([]gpu.Device, error) {
			return []gpu.Device{{MemoryFree: 1024 * 1024 * 1024}}, nil
		},
		Inspect: func(string) (BundleInfo, error) { return BundleInfo{MinVRAMMiB: 2048}, nil },
	})
	if _, err := m.Load(context.Background(), "demo:1"); !errors.Is(err, ErrResourceExhausted) {
		t.Fatalf("load error = %v", err)
	}
}

// Only resources.min_vram_mib gates admission: no declared value means the
// bundle is admitted, and the exact requirement needs no extra margin.
func TestVRAMAdmissionUsesBundleRequirementOnly(t *testing.T) {
	cases := []struct {
		name  string
		free  int64
		min   int64
		allow bool
	}{
		{name: "no requirement", free: 256 * 1024 * 1024, min: 0, allow: true},
		{name: "exact match", free: 4096 * 1024 * 1024, min: 4096, allow: true},
		{name: "one MiB short", free: 4095 * 1024 * 1024, min: 4096, allow: false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			free := tc.free
			m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{
				GPU: func(context.Context) ([]gpu.Device, error) {
					return []gpu.Device{{MemoryFree: free}}, nil
				},
				Inspect: func(string) (BundleInfo, error) {
					return BundleInfo{MinVRAMMiB: tc.min}, nil
				},
			})
			_, err := m.Load(context.Background(), "demo:1")
			if tc.allow && err != nil {
				t.Fatalf("expected admission, got %v", err)
			}
			if !tc.allow && !errors.Is(err, ErrResourceExhausted) {
				t.Fatalf("expected ErrResourceExhausted, got %v", err)
			}
		})
	}
}

// An app model start must go through the same admission as a model-page load.
func TestManagerUnloadIfLoaded(t *testing.T) {
	m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{
		GPU: func(context.Context) ([]gpu.Device, error) {
			return []gpu.Device{{MemoryFree: 16 * 1024 * 1024 * 1024}}, nil
		},
		Inspect: func(string) (BundleInfo, error) { return BundleInfo{}, nil },
	})
	if handled, err := m.UnloadIfLoaded(context.Background(), "demo:1"); handled || err != nil {
		t.Fatalf("unknown ref: handled=%v err=%v", handled, err)
	}
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if handled, err := m.UnloadIfLoaded(context.Background(), "demo:1"); !handled || err != nil {
		t.Fatalf("loaded ref: handled=%v err=%v", handled, err)
	}
	if loaded, _ := m.Slots(); loaded != 0 {
		t.Fatalf("slot not freed: loaded = %d", loaded)
	}
}

// A child that died outside the Manager must not be reused: Load starts a
// fresh process, and List stops advertising it.
func TestManagerDropsDeadInstances(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	l.procs[0].stopped = true
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if len(l.procs) != 2 {
		t.Fatalf("processes = %d, want 2 (dead instance was reused)", len(l.procs))
	}
	l.procs[1].stopped = true
	if got := m.List(); len(got) != 0 {
		t.Fatalf("List = %+v, want no dead instance", got)
	}
}

// Two applications using the same bundle share one process; it stops only when
// the last owner releases it.
func TestManagerSharedModelStaysUntilLastOwner(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	if _, err := m.LoadFor(context.Background(), "demo:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.LoadFor(context.Background(), "demo:1", "app:b"); err != nil {
		t.Fatal(err)
	}
	if len(l.procs) != 1 {
		t.Fatalf("processes = %d, want 1 shared", len(l.procs))
	}
	handled, err := m.ReleaseFor(context.Background(), "demo:1", "app:a")
	if !handled || err != nil {
		t.Fatalf("release a: handled=%v err=%v", handled, err)
	}
	if l.procs[0].stopped {
		t.Fatal("model stopped while app:b still owns it")
	}
	if loaded, _ := m.Slots(); loaded != 1 {
		t.Fatalf("loaded = %d, want 1", loaded)
	}
	handled, err = m.ReleaseFor(context.Background(), "demo:1", "app:b")
	if !handled || err != nil {
		t.Fatalf("release b: handled=%v err=%v", handled, err)
	}
	if !l.procs[0].stopped {
		t.Fatal("last owner did not stop the model")
	}
	if loaded, _ := m.Slots(); loaded != 0 {
		t.Fatalf("loaded = %d, want 0", loaded)
	}
}

// A model loaded from the model page is not unloaded when an app that reused it
// stops; the model page unload is the explicit override.
func TestManagerModelPageOwnership(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.LoadFor(context.Background(), "demo:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.ReleaseFor(context.Background(), "demo:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	if l.procs[0].stopped {
		t.Fatal("model page instance stopped by an app release")
	}
	if err := m.Unload(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if !l.procs[0].stopped {
		t.Fatal("model page unload did not stop the model")
	}
}

// The app launcher must record the owner from the request context so stopping
// one app does not release a model another app still uses.
func TestManagerClaimOnlyForResidentModels(t *testing.T) {
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect})
	if m.Claim("demo:1", "app:a") {
		t.Fatal("claimed a model that is not resident")
	}
	if len(l.procs) != 0 {
		t.Fatalf("claim started %d processes", len(l.procs))
	}
	if _, err := m.LoadFor(context.Background(), "demo:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	if !m.Claim("demo:1", "app:b") {
		t.Fatal("claim on a resident model failed")
	}
	if _, err := m.ReleaseFor(context.Background(), "demo:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	if l.procs[0].stopped {
		t.Fatal("model stopped while claim owner app:b is present")
	}
}

// A model-page load is persisted and restored by the next daemon; app-only
// models are restored from the app registry instead.
func TestManagerRestoresModelPageState(t *testing.T) {
	state := filepath.Join(t.TempDir(), "models.json")
	l := &fakeLauncher{}
	m := NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect, StatePath: state})
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	if _, err := m.LoadFor(context.Background(), "app:1", "app:a"); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(state)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(blob), "demo:1") {
		t.Fatalf("model-page ref not persisted: %s", blob)
	}
	if strings.Contains(string(blob), "app:1") {
		t.Fatalf("app-owned model must not be persisted as a model-page load: %s", blob)
	}

	l2 := &fakeLauncher{}
	m2 := NewManagerWithOptions(l2, ManagerOptions{Inspect: fakeInspect, StatePath: state})
	if errs := m2.RestoreModels(context.Background()); len(errs) != 0 {
		t.Fatalf("restore errors: %v", errs)
	}
	if _, ok := m2.Endpoint("demo:1"); !ok {
		t.Fatal("demo:1 not restored")
	}
	if len(l2.procs) != 1 {
		t.Fatalf("restored processes = %d, want 1", len(l2.procs))
	}
	if err := m2.Unload(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	blob, _ = os.ReadFile(state)
	if strings.Contains(string(blob), "demo:1") {
		t.Fatalf("unload did not persist: %s", blob)
	}
}

// A failed restore keeps the saved intent so the next start can retry.
func TestManagerRestoreKeepsFailedModels(t *testing.T) {
	state := filepath.Join(t.TempDir(), "models.json")
	if err := os.WriteFile(state, []byte(`{"models":["ok:1","bad:1"]}`), 0o644); err != nil {
		t.Fatal(err)
	}
	m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{
		StatePath: state,
		Inspect: func(refStr string) (BundleInfo, error) {
			if refStr == "bad:1" {
				return BundleInfo{}, errors.New("boom")
			}
			return BundleInfo{}, nil
		},
	})
	errs := m.RestoreModels(context.Background())
	if len(errs) != 1 {
		t.Fatalf("restore errors = %v, want one", errs)
	}
	blob, _ := os.ReadFile(state)
	if !strings.Contains(string(blob), "ok:1") || !strings.Contains(string(blob), "bad:1") {
		t.Fatalf("saved intent changed after a partial restore: %s", blob)
	}
}

// Re-syncing a cached version passes Force to the puller; a loaded model must
// be unloaded first.
func TestPullForceAndBusy(t *testing.T) {
	p := &capturePuller{}
	s := &Server{Puller: p, Jobs: NewJobManager()}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/pull", strings.NewReader(`{"ref":"demo:1","force":true}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d: %s", rec.Code, rec.Body.String())
	}
	deadline := time.Now().Add(2 * time.Second)
	for !p.force && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if !p.force {
		t.Fatal("pull did not receive force")
	}

	m := NewManagerWithOptions(&fakeLauncher{}, ManagerOptions{Inspect: fakeInspect})
	if _, err := m.Load(context.Background(), "demo:1"); err != nil {
		t.Fatal(err)
	}
	s.Manager = m
	req = httptest.NewRequest(http.MethodPost, "/api/v1/pull", strings.NewReader(`{"ref":"demo:1"}`))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusConflict {
		t.Fatalf("loaded model pull status = %d, want 409", rec.Code)
	}
}

type capturePuller struct {
	force bool
}

func (p *capturePuller) Pull(ctx context.Context, ref string, opts host.PullOptions) (host.PullResult, error) {
	p.force = opts.Force
	if opts.Progress != nil {
		opts.Progress(host.PullEvent{Phase: "done", Ref: ref})
	}
	return host.PullResult{BundleRoot: "/tmp/bundle", Checkpoint: "/tmp/weights"}, nil
}

func TestInspectBundleVRAM(t *testing.T) {
	dir := t.TempDir()
	data := `{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "vram-test",
  "python_abi": "310",
  "entry": {"run": {"module": "run", "attr": "RunEngine"}},
  "python_dependencies": {"pip": []},
  "runtime": {"sm89-cu124-linux-x86_64-py310": "runtime/test"},
  "resources": {"min_vram_mib": 8192}
}`
	if err := os.WriteFile(filepath.Join(dir, "flashcli-bundle.json"), []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
	info, err := inspectBundle(dir)
	if err != nil {
		t.Fatal(err)
	}
	if info.MinVRAMMiB != 8192 {
		t.Fatalf("MinVRAMMiB = %d", info.MinVRAMMiB)
	}
}

type gatePuller struct {
	started chan struct{}
	release chan struct{}
}

func (p *gatePuller) Pull(ctx context.Context, ref string, opts host.PullOptions) (host.PullResult, error) {
	select {
	case p.started <- struct{}{}:
		<-p.release
	default:
	}
	return host.PullResult{BundleRoot: "/tmp/bundle", Checkpoint: "/tmp/weights"}, nil
}

func TestPullRejectsConcurrent(t *testing.T) {
	p := &gatePuller{started: make(chan struct{}), release: make(chan struct{})}
	s := &Server{Source: fakeSource{}, Puller: p, Jobs: NewJobManager()}
	post := func() int {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/pull", strings.NewReader(`{"ref":"demo:1"}`))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		return rec.Code
	}
	if code := post(); code != http.StatusAccepted {
		t.Fatalf("first pull status = %d", code)
	}
	<-p.started
	if code := post(); code != http.StatusConflict {
		t.Fatalf("concurrent pull status = %d, want 409", code)
	}
	close(p.release)
	for i := 0; i < 100 && s.pullBusy.Load(); i++ {
		time.Sleep(10 * time.Millisecond)
	}
	if code := post(); code != http.StatusAccepted {
		t.Fatalf("pull after completion status = %d", code)
	}
}
func TestMirrorAPI(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	s := &Server{}
	call := func(method, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, "/api/v1/mirror", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		return rec
	}
	if rec := call(http.MethodGet, ""); rec.Code != http.StatusOK {
		t.Fatalf("GET status = %d", rec.Code)
	}
	if rec := call(http.MethodPost, `{"enabled":true}`); rec.Code != http.StatusOK {
		t.Fatalf("POST enable status = %d: %s", rec.Code, rec.Body.String())
	}
	if rec := call(http.MethodGet, ""); !strings.Contains(rec.Body.String(), `"enabled":true`) {
		t.Fatalf("GET after enable = %s", rec.Body.String())
	}
	if rec := call(http.MethodPost, `{"enabled":false}`); rec.Code != http.StatusOK {
		t.Fatalf("POST disable status = %d", rec.Code)
	}
}
