package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/gpu"
)

// staticLauncher returns a fixed endpoint so HTTP handlers can proxy to a test
// server without spawning flashcli.
type staticLauncher struct {
	endpoint string
	err      error
	procs    []*fakeServe
}

func (l *staticLauncher) Start(_ context.Context, refStr string, _ int) (ServeProcess, error) {
	if l.err != nil {
		return nil, l.err
	}
	p := &fakeServe{ref: refStr, endpoint: l.endpoint}
	l.procs = append(l.procs, p)
	return p, nil
}

func newFlowServer(t *testing.T, l Launcher) *Server {
	t.Helper()
	store := newServeSettingsStore(filepath.Join(t.TempDir(), "serve-options.json"))
	return &Server{
		Source:        fakeSource{},
		Puller:        fakePuller{},
		Jobs:          NewJobManager(),
		Manager:       NewManagerWithOptions(l, ManagerOptions{Inspect: fakeInspect, ServeSettings: store}),
		GPU:           func(context.Context) ([]gpu.Device, error) { return []gpu.Device{}, nil },
		LogDir:        t.TempDir(),
		Started:       time.Now(),
		ServeSettings: store,
	}
}

func call(t *testing.T, h http.Handler, method, path, body string) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()
	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, reader)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var decoded map[string]any
	if strings.HasPrefix(rec.Header().Get("Content-Type"), "application/json") {
		_ = json.Unmarshal(rec.Body.Bytes(), &decoded)
	}
	return rec, decoded
}

func TestModelLifecycleOverHTTP(t *testing.T) {
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("proxied path = %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chat","choices":[]}`)
	}))
	defer model.Close()

	s := newFlowServer(t, &staticLauncher{endpoint: model.URL})
	h := s.Handler()

	rec, body := call(t, h, http.MethodPost, "/v1/models/load", `{"ref":"demo:1"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("load = %d: %s", rec.Code, rec.Body.String())
	}
	if body["endpoint"] != model.URL {
		t.Fatalf("endpoint = %v", body["endpoint"])
	}

	rec, body = call(t, h, http.MethodGet, "/v1/models", "")
	if rec.Code != http.StatusOK || len(body["loaded"].([]any)) != 1 {
		t.Fatalf("models = %d: %s", rec.Code, rec.Body.String())
	}

	rec, body = call(t, h, http.MethodGet, "/v1/models/loaded", "")
	if rec.Code != http.StatusOK || len(body["models"].([]any)) != 1 {
		t.Fatalf("loaded = %d: %s", rec.Code, rec.Body.String())
	}

	rec, body = call(t, h, http.MethodGet, "/v1/resources", "")
	if rec.Code != http.StatusOK || body["loaded_count"].(float64) != 1 {
		t.Fatalf("resources = %d: %s", rec.Code, rec.Body.String())
	}

	rec, body = call(t, h, http.MethodPost, "/v1/ui/chat",
		`{"ref":"demo:1","body":{"model":"demo","messages":[]}}`)
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"id":"chat"`) {
		t.Fatalf("ui chat = %d: %s", rec.Code, rec.Body.String())
	}

	rec, _ = call(t, h, http.MethodPost, "/v1/ui/chat", `{"ref":"other:1","body":{}}`)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("ui chat unknown ref = %d", rec.Code)
	}
	rec, _ = call(t, h, http.MethodPost, "/v1/ui/chat", `{"body":{}}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("ui chat missing ref = %d", rec.Code)
	}

	rec, _ = call(t, h, http.MethodPost, "/v1/models/load", `{}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("load without ref = %d", rec.Code)
	}
	rec, _ = call(t, h, http.MethodPost, "/v1/models/unload", `{"ref":"demo:1"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("unload = %d: %s", rec.Code, rec.Body.String())
	}
	rec, body = call(t, h, http.MethodGet, "/v1/models/loaded", "")
	if rec.Code != http.StatusOK || len(body["models"].([]any)) != 0 {
		t.Fatalf("loaded after unload = %s", rec.Body.String())
	}
}

func TestSystemLogsAndAssetsOverHTTP(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()

	logPath := filepath.Join(s.LogDir, serveLogName("demo:1"))
	if err := os.WriteFile(logPath, []byte("line1\nline2\nline3\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	rec, body := call(t, h, http.MethodGet, "/v1/system", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("system = %d: %s", rec.Code, rec.Body.String())
	}
	if body["version"] == "" || body["os"] == "" {
		t.Fatalf("system body = %s", rec.Body.String())
	}

	if rec, _ := call(t, h, http.MethodGet, "/v1/version", ""); rec.Code != http.StatusOK {
		t.Fatalf("version = %d", rec.Code)
	}

	rec, body = call(t, h, http.MethodGet, "/v1/logs?kind=model&ref=demo:1&lines=2", "")
	if rec.Code != http.StatusOK || body["kind"] != "model" {
		t.Fatalf("model logs = %d: %s", rec.Code, rec.Body.String())
	}
	if lines := body["lines"].([]any); len(lines) != 2 || lines[1] != "line3" {
		t.Fatalf("model log lines = %v", lines)
	}
	if rec, _ := call(t, h, http.MethodGet, "/v1/logs?kind=model", ""); rec.Code != http.StatusBadRequest {
		t.Fatalf("model logs without ref = %d", rec.Code)
	}
	if rec, _ := call(t, h, http.MethodGet, "/v1/logs?kind=server&lines=1", ""); rec.Code != http.StatusOK {
		t.Fatalf("server logs = %d", rec.Code)
	}

	rec, _ = call(t, h, http.MethodGet, "/v1/logs/download?kind=model&ref=demo:1", "")
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "line3") {
		t.Fatalf("download model log = %d: %s", rec.Code, rec.Body.String())
	}
	rec, _ = call(t, h, http.MethodGet, "/v1/logs/download", "")
	if rec.Code != http.StatusOK || !strings.Contains(rec.Header().Get("Content-Disposition"), "flashserver.log") {
		t.Fatalf("download server log = %d", rec.Code)
	}

	for _, path := range []string{"/", "/docs", "/openapi.yaml"} {
		rec, _ := call(t, h, http.MethodGet, path, "")
		if rec.Code != http.StatusOK || rec.Body.Len() == 0 {
			t.Fatalf("%s = %d (%d bytes)", path, rec.Code, rec.Body.Len())
		}
	}
	if rec, _ := call(t, h, http.MethodGet, "/ui/missing-file.js", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("missing asset = %d", rec.Code)
	}

	for _, path := range []string{"/v1/gpu", "/v1/gpu/history?seconds=1", "/v1/system/history"} {
		if rec, _ := call(t, h, http.MethodGet, path, ""); rec.Code != http.StatusOK {
			t.Fatalf("%s = %d", path, rec.Code)
		}
	}
}

func TestJobsOverHTTP(t *testing.T) {
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	h := s.Handler()

	rec, body := call(t, h, http.MethodPost, "/v1/pull", `{"ref":"demo:1"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("pull = %d: %s", rec.Code, rec.Body.String())
	}
	id, _ := body["job_id"].(string)
	if id == "" {
		t.Fatalf("no job id: %s", rec.Body.String())
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		rec, body = call(t, h, http.MethodGet, "/v1/jobs/"+id, "")
		if rec.Code != http.StatusOK {
			t.Fatalf("job = %d: %s", rec.Code, rec.Body.String())
		}
		state, _ := body["state"].(string)
		if state == "done" || state == "failed" {
			if state != "done" {
				t.Fatalf("job state = %s", state)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("job did not finish: %s", rec.Body.String())
		}
		time.Sleep(20 * time.Millisecond)
	}

	rec, _ = call(t, h, http.MethodGet, "/v1/jobs/"+id+"/events", "")
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "event: done") {
		t.Fatalf("events = %d: %s", rec.Code, rec.Body.String())
	}

	if rec, _ := call(t, h, http.MethodGet, "/v1/jobs/unknown", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown job = %d", rec.Code)
	}
	if rec, _ := call(t, h, http.MethodGet, "/v1/jobs/unknown/events", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown job events = %d", rec.Code)
	}
	if rec, _ := call(t, h, http.MethodPost, "/v1/jobs/unknown/cancel", ""); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown job cancel = %d", rec.Code)
	}
}

func TestRunServesUntilContextCancel(t *testing.T) {
	port, err := freePort()
	if err != nil {
		t.Fatal(err)
	}
	s := newFlowServer(t, &staticLauncher{endpoint: "http://127.0.0.1:1"})
	s.Addr = fmt.Sprintf("127.0.0.1:%d", port)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()

	url := "http://" + s.Addr + "/health"
	var lastErr error
	for i := 0; i < 100; i++ {
		resp, err := http.Get(url)
		if err == nil {
			_, _ = io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				lastErr = nil
				break
			}
			lastErr = fmt.Errorf("status %d", resp.StatusCode)
		} else {
			lastErr = err
		}
		time.Sleep(20 * time.Millisecond)
	}
	if lastErr != nil {
		cancel()
		t.Fatalf("health never became ready: %v", lastErr)
	}

	// The real listener answers the version endpoint too.
	resp, err := http.Get("http://" + s.Addr + "/v1/version")
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	blob, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if !bytes.Contains(blob, []byte("version")) {
		cancel()
		t.Fatalf("version body = %s", blob)
	}

	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run returned %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("Run did not stop")
	}
}
