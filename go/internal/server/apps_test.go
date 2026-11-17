package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

const appManifestFixture = `{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "demo",
  "version": "1.0.0",
  "display_name": "Demo",
  "supported": {"os": ["linux"], "arch": ["x86_64", "arm64"]},
  "install": {"commands": {"linux": "echo install-ok"}},
  "model": {"bundles": [{"bundle": "a/one:1", "default": true, "serve": {"options": {}}}]},
  "config": []
}`

type appFakeProc struct {
	ref      string
	endpoint string
	pid      int
	stopped  bool
}

func (p *appFakeProc) Ref() string                   { return p.ref }
func (p *appFakeProc) Endpoint() string              { return p.endpoint }
func (p *appFakeProc) PID() int                      { return p.pid }
func (p *appFakeProc) Healthy(context.Context) error { return nil }
func (p *appFakeProc) Running() bool                 { return !p.stopped }
func (p *appFakeProc) LastLog() string               { return "" }
func (p *appFakeProc) Stop(context.Context) error    { p.stopped = true; return nil }

type appFakeLauncher struct {
	procs []*appFakeProc
	next  int
}

func (l *appFakeLauncher) StartWithOptions(_ context.Context, ref string, opts modelrun.LoadOptions) (modelrun.ServeProcess, error) {
	l.next++
	p := &appFakeProc{ref: ref, endpoint: fmt.Sprintf("http://127.0.0.1:%d", 21000+l.next), pid: 3000 + l.next}
	l.procs = append(l.procs, p)
	return p, nil
}

func newAppTestServer(t *testing.T) (*Server, *httptest.Server, *appFakeLauncher) {
	t.Helper()
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/apps":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"code": 0,
				"data": map[string]any{
					"list": []map[string]any{{
						"id": 1, "name": "demo", "display_name": "Demo", "domain": "通用Agent",
						"version": "1.0.0", "organization": map[string]string{"name": "xym"},
						"supported_os": []string{"linux"}, "supported_arch": []string{"x86_64"},
						"model_bundles": []map[string]any{{"bundle": "a/one:1", "is_default": true}},
					}},
					"total": 1, "page": 1, "page_size": 20,
				},
			})
		case "/api/v1/apps/xym/demo":
			_, _ = w.Write([]byte(`{"code":0,"message":"success","data":` + appManifestFixture + `}`))
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(hub.Close)
	t.Setenv("FLASHCLI_FLASHHUB_API", hub.URL+"/api/v1/repos")
	home := t.TempDir()
	t.Setenv("FLASHCLI_HOME", home)

	launcher := &appFakeLauncher{}
	svc := apps.New(home)
	svc.Launcher = launcher
	svc.Prepare = func(context.Context, string) error { return nil }
	svc.Fetch = func(ctx context.Context, ref flashhub.AppRef) ([]byte, error) {
		return []byte(appManifestFixture), nil
	}

	s := &Server{Source: fakeSource{}, Jobs: NewJobManager(), AppService: func() *apps.Service { return svc }}
	ts := httptest.NewServer(s.Handler())
	t.Cleanup(ts.Close)
	return s, ts, launcher
}

func appRequest(t *testing.T, method, url string, body string) (int, map[string]any) {
	t.Helper()
	req, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

func TestAppEndpointsLifecycle(t *testing.T) {
	s, ts, launcher := newAppTestServer(t)
	base := ts.URL

	status, body := appRequest(t, http.MethodGet, base+"/v1/apps?page=1", "")
	if status != 200 || len(body["apps"].([]any)) != 1 {
		t.Fatalf("list = %d %v", status, body)
	}

	status, body = appRequest(t, http.MethodGet, base+"/v1/apps/xym/demo", "")
	if status != 200 || body["manifest"] == nil {
		t.Fatalf("manifest = %d %v", status, body)
	}

	status, body = appRequest(t, http.MethodPost, base+"/v1/apps/xym/demo/prepare", `{"version":"1.0.0"}`)
	if status != 202 {
		t.Fatalf("prepare = %d %v", status, body)
	}
	id, _ := body["job_id"].(string)
	deadline := time.Now().Add(5 * time.Second)
	for {
		if job, ok := s.Jobs.Get(id); ok {
			job.mu.Lock()
			state := job.State
			job.mu.Unlock()
			if state == "done" {
				break
			}
			if state == "failed" {
				t.Fatalf("prepare job failed")
			}
		}
		if time.Now().After(deadline) {
			t.Fatal("prepare job did not finish")
		}
		time.Sleep(20 * time.Millisecond)
	}

	status, body = appRequest(t, http.MethodGet, base+"/v1/apps/installed", "")
	if status != 200 || body["apps"].(map[string]any)["xym/demo:1.0.0"] == nil {
		t.Fatalf("installed = %d %v", status, body)
	}

	status, body = appRequest(t, http.MethodPost, base+"/v1/apps/xym/demo/start?version=1.0.0", "")
	if status != 200 || body["state"] != "ready" {
		t.Fatalf("start = %d %v", status, body)
	}
	if len(launcher.procs) != 1 {
		t.Fatalf("launcher started %d", len(launcher.procs))
	}

	status, body = appRequest(t, http.MethodGet, base+"/v1/apps/xym/demo/status?version=1.0.0", "")
	if status != 200 || len(body["models"].([]any)) != 1 {
		t.Fatalf("status = %d %v", status, body)
	}

	status, body = appRequest(t, http.MethodPost, base+"/v1/apps/xym/demo/stop?version=1.0.0", "")
	if status != 200 || body["state"] != "stopped" {
		t.Fatalf("stop = %d %v", status, body)
	}
	if !launcher.procs[0].stopped {
		t.Fatal("model was not stopped")
	}

	status, _ = appRequest(t, http.MethodDelete, base+"/v1/apps/xym/demo?version=1.0.0", "")
	if status != 200 {
		t.Fatalf("uninstall = %d", status)
	}
	status, _ = appRequest(t, http.MethodGet, base+"/v1/apps/xym/demo/status?version=1.0.0", "")
	if status != 404 {
		t.Fatalf("status after uninstall = %d", status)
	}
}
