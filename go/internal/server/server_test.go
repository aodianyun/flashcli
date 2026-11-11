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
		{"/v1/models", "models"},
		{"/v1/storage", "areas"},
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
	req := httptest.NewRequest(http.MethodPost, "/v1/pull", nil)
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
	req := httptest.NewRequest(http.MethodPost, "/v1/pull", strings.NewReader(`{"ref":"demo:1"}`))
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
}

func (f *fakeServe) Ref() string                   { return f.ref }
func (f *fakeServe) Endpoint() string              { return f.endpoint }
func (f *fakeServe) PID() int                      { return 1234 }
func (f *fakeServe) Healthy(context.Context) error { return nil }
func (f *fakeServe) Running() bool                 { return !f.stopped }
func (f *fakeServe) LastLog() string               { return "" }
func (f *fakeServe) Stop(context.Context) error    { f.stopped = true; return nil }

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
	req := httptest.NewRequest(http.MethodGet, "/v1/gpu", nil)
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
	for _, path := range []string{"/v1/resources", "/v1/models/loaded", "/v1/version"} {
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
	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d", rec.Code)
	}
	req = httptest.NewRequest(http.MethodGet, "/v1/models", nil)
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
		req := httptest.NewRequest(http.MethodPost, "/v1/pull", strings.NewReader(`{"ref":"demo:1"}`))
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
