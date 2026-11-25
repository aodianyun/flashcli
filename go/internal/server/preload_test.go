package server

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/gpu"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

type blockingPuller struct {
	mu      sync.Mutex
	calls   int
	started chan struct{}
	release chan struct{}
	err     error
	once    sync.Once
}

func (p *blockingPuller) Pull(ctx context.Context, _ string, _ host.PullOptions) (host.PullResult, error) {
	p.mu.Lock()
	p.calls++
	p.mu.Unlock()
	if p.started != nil {
		p.once.Do(func() { close(p.started) })
	}
	if p.release != nil {
		select {
		case <-p.release:
		case <-ctx.Done():
			return host.PullResult{}, ctx.Err()
		}
	}
	return host.PullResult{}, p.err
}

func (p *blockingPuller) callCount() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.calls
}

func newPreloadServer(t *testing.T, p Puller) *Server {
	t.Helper()
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	return &Server{
		Source:  fakeSource{},
		Puller:  p,
		Jobs:    NewJobManager(),
		Preload: newPreloadStore(filepath.Join(t.TempDir(), "preload.json")),
		LogDir:  t.TempDir(),
		Started: time.Now(),
		Inspect: func(string) (BundleInfo, error) { return BundleInfo{}, nil },
	}
}

func waitJobState(t *testing.T, jobs *JobManager, id string) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		j, ok := jobs.Get(id)
		if !ok {
			t.Fatalf("job %s not found", id)
		}
		j.mu.Lock()
		state := j.State
		j.mu.Unlock()
		if state == "done" || state == "failed" {
			return state
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("job %s did not finish", id)
	return ""
}

func findModel(t *testing.T, body map[string]any, refStr string) map[string]any {
	t.Helper()
	models, ok := body["models"].([]any)
	if !ok {
		t.Fatalf("models = %v", body["models"])
	}
	for _, raw := range models {
		m, ok := raw.(map[string]any)
		if ok && m["ref"] == refStr {
			return m
		}
	}
	return nil
}

func TestPreloadDedupesAndBecomesPreloaded(t *testing.T) {
	p := &blockingPuller{started: make(chan struct{}), release: make(chan struct{})}
	s := newPreloadServer(t, p)
	h := s.Handler()
	refStr := "flashcli-bundle/demo:1.0.0"

	rec, body := call(t, h, http.MethodPost, "/api/v1/models/preload", `{"ref":"`+refStr+`"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("preload = %d: %s", rec.Code, rec.Body.String())
	}
	jobID, _ := body["job_id"].(string)
	if jobID == "" || body["preload"] != preloadLoading {
		t.Fatalf("preload body = %v", body)
	}
	<-p.started

	// A concurrent preload for the same ref shares the running job.
	rec, body = call(t, h, http.MethodPost, "/api/v1/models/preload", `{"ref":"`+refStr+`"}`)
	if rec.Code != http.StatusAccepted || body["job_id"] != jobID {
		t.Fatalf("second preload = %d: %v", rec.Code, body)
	}
	if p.callCount() != 1 {
		t.Fatalf("puller calls = %d, want 1", p.callCount())
	}

	close(p.release)
	if state := waitJobState(t, s.Jobs, jobID); state != "done" {
		t.Fatalf("job state = %s", state)
	}

	// Idempotent: a completed preload returns its state without a new job.
	rec, body = call(t, h, http.MethodPost, "/api/v1/models/preload", `{"ref":"`+refStr+`"}`)
	if rec.Code != http.StatusOK || body["preload"] != preloadReady {
		t.Fatalf("third preload = %d: %v", rec.Code, body)
	}
	if p.callCount() != 1 {
		t.Fatalf("puller calls = %d, want 1", p.callCount())
	}

	rec, body = call(t, h, http.MethodGet, "/api/v1/models", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("models = %d", rec.Code)
	}
	model := findModel(t, body, refStr)
	if model == nil || model["preload"] != preloadReady || model["resident"] != "stopped" {
		t.Fatalf("model view = %v", model)
	}

	rec, body = call(t, h, http.MethodGet, "/v1/models", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("gateway models = %d", rec.Code)
	}
	data, _ := body["data"].([]any)
	found := false
	for _, raw := range data {
		if entry, ok := raw.(map[string]any); ok && entry["id"] == refStr {
			found = true
		}
	}
	if !found {
		t.Fatalf("gateway list does not contain preloaded ref: %v", body)
	}
}

func TestPreloadFailureReturnsToAbsent(t *testing.T) {
	p := &blockingPuller{err: errors.New("network down")}
	s := newPreloadServer(t, p)
	h := s.Handler()
	refStr := "flashcli-bundle/broken:1.0.0"

	rec, body := call(t, h, http.MethodPost, "/api/v1/models/preload", `{"ref":"`+refStr+`"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("preload = %d: %s", rec.Code, rec.Body.String())
	}
	jobID, _ := body["job_id"].(string)
	if state := waitJobState(t, s.Jobs, jobID); state != "failed" {
		t.Fatalf("job state = %s", state)
	}
	if got := s.preloads().state(refStr); got != preloadAbsent {
		t.Fatalf("preload state = %s", got)
	}
	rec, body = call(t, h, http.MethodGet, "/api/v1/models", "")
	if rec.Code != http.StatusOK || findModel(t, body, refStr) != nil {
		t.Fatalf("failed ref should not be listed: %v", body)
	}
}

func TestUnloadBusyWaitsOrForces(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()
	if _, err := s.Manager.LoadFor(context.Background(), "demo:1", "test"); err != nil {
		t.Fatal(err)
	}

	rec, body := call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("unload busy = %d: %s", rec.Code, rec.Body.String())
	}
	errBody, _ := body["error"].(map[string]any)
	if errBody["code"] != "model_busy" {
		t.Fatalf("error = %v", body)
	}

	// Stop the resident while unload waits.
	go func() {
		time.Sleep(150 * time.Millisecond)
		_ = s.Manager.Unload(context.Background(), "demo:1")
	}()
	rec, body = call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1","wait_seconds":2}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("unload wait = %d: %s", rec.Code, rec.Body.String())
	}
	if body["preload"] != preloadAbsent || body["removed"] != false {
		t.Fatalf("unload body = %v", body)
	}

	// A busy model with force stops first, then deletes.
	if _, err := s.Manager.LoadFor(context.Background(), "demo:1", "test"); err != nil {
		t.Fatal(err)
	}
	rec, body = call(t, h, http.MethodPost, "/api/v1/models/unload", `{"ref":"demo:1","force":true}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("unload force = %d: %s", rec.Code, rec.Body.String())
	}
	if len(s.Manager.List()) != 0 {
		t.Fatalf("resident still present after force unload")
	}
}

func TestUnloadRemovesCacheAndReportsSharedAssets(t *testing.T) {
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)
	keys := []string{"a/1.0.0", "b/1.0.0"}
	refs := []string{"a:1.0.0", "b:1.0.0"}
	roots := make([]string, len(keys))
	for i, key := range keys {
		roots[i] = filepath.Join(paths.Bundles(), filepath.FromSlash(key))
		if err := os.MkdirAll(roots[i], 0o755); err != nil {
			t.Fatal(err)
		}
		marker, _ := json.Marshal(map[string]any{
			"ref": refs[i], "cache_key": key, "bundle_root": roots[i],
			"weights_key": "shared/weights", "runtime_id": "shared-runtime",
		})
		if err := os.WriteFile(filepath.Join(roots[i], flashhub.MarkerName), marker, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	weightsDir := filepath.Join(paths.Models(), "shared", "weights")
	if err := os.MkdirAll(weightsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(weightsDir, "weights.bin"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := runtime.WriteMarker("shared-runtime", map[string]any{
		"runtime_id": "shared-runtime", "bundle_root": roots[0],
	}); err != nil {
		t.Fatal(err)
	}
	runtimeDir := runtime.Dir("shared-runtime")
	if err := os.WriteFile(filepath.Join(runtimeDir, "torch.bin"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}

	s := &Server{Preload: newPreloadStore(filepath.Join(t.TempDir(), "preload.json"))}
	rec, body := call(t, s.Handler(), http.MethodPost, "/api/v1/models/unload", `{"ref":"a:1.0.0"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("unload = %d: %s", rec.Code, rec.Body.String())
	}
	if body["removed"] != true || body["shared_weights"] != true || body["shared_runtime"] != true {
		t.Fatalf("unload body = %v", body)
	}
	if _, err := os.Stat(roots[0]); !os.IsNotExist(err) {
		t.Fatalf("target bundle still exists: %v", err)
	}
	if _, err := os.Stat(roots[1]); err != nil {
		t.Fatalf("other bundle removed: %v", err)
	}
	if _, err := os.Stat(weightsDir); err != nil {
		t.Fatalf("shared weights removed: %v", err)
	}
	if _, err := os.Stat(runtimeDir); err != nil {
		t.Fatalf("shared runtime removed: %v", err)
	}
}

func TestPreloadStatePersistsAcrossStoreReload(t *testing.T) {
	path := filepath.Join(t.TempDir(), "preload.json")
	first := newPreloadStore(path)
	first.setState("flashcli-bundle/demo:1.0.0", preloadReady, "")
	second := newPreloadStore(path)
	if got := second.state("flashcli-bundle/demo:1.0.0"); got != preloadReady {
		t.Fatalf("state after reload = %s", got)
	}
	second.setState("flashcli-bundle/demo:1.0.0", preloadAbsent, "")
	third := newPreloadStore(path)
	if got := third.state("flashcli-bundle/demo:1.0.0"); got != preloadAbsent {
		t.Fatalf("state after removal = %s", got)
	}
}

func TestReconcilePreloadsDropsStaleIntent(t *testing.T) {
	s := newPreloadServer(t, &blockingPuller{})
	s.Preload.setState("demo:1", preloadReady, "")
	s.Preload.setState("flashcli-bundle/other:1.0.0", preloadLoading, "preload-1")
	s.reconcilePreloads(context.Background())
	if got := s.Preload.state("demo:1"); got != preloadAbsent {
		t.Fatalf("stale preloaded state = %s", got)
	}
	if got := s.Preload.state("flashcli-bundle/other:1.0.0"); got != preloadAbsent {
		t.Fatalf("in-flight state = %s", got)
	}
}

func TestPreloadRejectsInsufficientTotalVRAM(t *testing.T) {
	s := newPreloadServer(t, &blockingPuller{})
	s.GPU = func(context.Context) ([]gpu.Device, error) {
		return []gpu.Device{{Index: 0, MemoryTotal: 8 << 30}}, nil
	}
	s.Inspect = func(string) (BundleInfo, error) {
		return BundleInfo{MinVRAMMiB: 12288, GPUCount: 1}, nil
	}
	rec, body := call(t, s.Handler(), http.MethodPost, "/api/v1/models/preload",
		`{"ref":"flashcli-bundle/demo:1.0.0"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("preload = %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(body["error"].(string), "12288 MiB") {
		t.Fatalf("error = %v", body)
	}
}
