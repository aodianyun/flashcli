package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"

	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

type gatewayLauncher struct {
	mu           sync.Mutex
	endpoint     string
	blockHealthy chan struct{}
	calls        int
}

func (l *gatewayLauncher) Start(ctx context.Context, refStr string, port int) (ServeProcess, error) {
	return l.StartWithOptions(ctx, refStr, modelrun.LoadOptions{Port: port})
}

func (l *gatewayLauncher) StartWithOptions(_ context.Context, refStr string, _ modelrun.LoadOptions) (ServeProcess, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.calls++
	return &fakeServe{ref: refStr, endpoint: l.endpoint, healthy: l.blockHealthy}, nil
}

func (l *gatewayLauncher) callCount() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.calls
}

type flipSource struct {
	ref   string
	ready atomic.Bool
	caps  []string
}

func (s *flipSource) Models(context.Context) ([]host.Model, error) {
	return []host.Model{{
		Ref: s.ref, CacheKey: "demo/1", BundleCached: true,
		WeightsCached: s.ready.Load(), Serve: true, Capabilities: s.caps,
	}}, nil
}
func (s *flipSource) Storage(context.Context) ([]host.Area, error) { return nil, nil }

func gatewayInspect(caps []string, m *manifest.Manifest) func(string) (BundleInfo, error) {
	return func(string) (BundleInfo, error) {
		return BundleInfo{Name: "demo", Manifest: m, Capabilities: caps}, nil
	}
}

func gatewayTestServer(t *testing.T, source Source, launcher Launcher, inspect func(string) (BundleInfo, error)) *Server {
	t.Helper()
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	manager := NewManagerWithOptions(launcher, ManagerOptions{Inspect: inspect})
	scheduler := NewScheduler(manager, SchedulerOptions{
		Inspect: inspect,
		Inventory: func(context.Context) DeviceInventory {
			return twoGPUInventory(28 << 30)
		},
		IdleStopSeconds: 3600,
	})
	return &Server{
		Source:                   source,
		Manager:                  manager,
		Scheduler:                scheduler,
		Jobs:                     NewJobManager(),
		Puller:                   fakePuller{},
		Preload:                  newPreloadStore(t.TempDir() + "/preload.json"),
		Started:                  time.Now(),
		ResidentStartWaitSeconds: 5,
		QueueTimeoutSeconds:      0,
		AutoPull:                 true,
	}
}

func TestGatewayChatProxyRewritesModelAndHidesEndpoint(t *testing.T) {
	var upstream map[string]any
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blob, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(blob, &upstream)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chatcmpl-1","object":"chat.completion","model":"child-model","choices":[]}`)
	}))
	defer child.Close()

	launcher := &gatewayLauncher{endpoint: child.URL}
	refStr := "flashcli-bundle/demo:1.0.0"
	source := &flipSource{ref: refStr, caps: []string{"openai.chat"}}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))

	rec, body := call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[{"role":"user","content":"hi"}]}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("chat = %d: %s", rec.Code, rec.Body.String())
	}
	if body["model"] != refStr {
		t.Fatalf("response model = %v", body["model"])
	}
	if upstream["model"] != refStr {
		t.Fatalf("upstream model = %v", upstream["model"])
	}
	if strings.Contains(rec.Body.String(), strings.TrimPrefix(child.URL, "http://")) {
		t.Fatalf("child endpoint leaked: %s", rec.Body.String())
	}
	if got := s.Scheduler.ActiveRequests(refStr); got != 0 {
		t.Fatalf("lease leaked: %d", got)
	}
	if launcher.callCount() != 1 {
		t.Fatalf("launcher calls = %d", launcher.callCount())
	}
}

func TestGatewaySSERewritesEveryEvent(t *testing.T) {
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher, _ := w.(http.Flusher)
		for _, payload := range []string{
			`{"id":"1","object":"chat.completion.chunk","model":"child","choices":[]}`,
			`{"id":"2","object":"chat.completion.chunk","model":"child","choices":[]}`,
		} {
			_, _ = io.WriteString(w, "data: "+payload+"\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		}
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	launcher := &gatewayLauncher{endpoint: child.URL}
	source := &flipSource{ref: refStr, caps: []string{"openai.chat"}}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/v1/chat/completions", "application/json",
		strings.NewReader(`{"model":"`+refStr+`","stream":true,"messages":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	blob, _ := io.ReadAll(resp.Body)
	text := string(blob)
	if strings.Count(text, `"model":"`+refStr+`"`) != 2 {
		t.Fatalf("SSE model rewrite failed: %s", text)
	}
	if !strings.Contains(text, "data: [DONE]") {
		t.Fatalf("SSE done marker lost: %s", text)
	}
	if strings.Contains(text, `"model":"child"`) {
		t.Fatalf("SSE model not rewritten: %s", text)
	}
}

func TestGatewayClientCancelReleasesLease(t *testing.T) {
	canceled := make(chan struct{})
	var once sync.Once
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher, _ := w.(http.Flusher)
		for {
			select {
			case <-r.Context().Done():
				once.Do(func() { close(canceled) })
				return
			case <-time.After(50 * time.Millisecond):
				if _, err := io.WriteString(w, "data: {\"model\":\"child\",\"choices\":[]}\n\n"); err != nil {
					return
				}
				if flusher != nil {
					flusher.Flush()
				}
			}
		}
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	launcher := &gatewayLauncher{endpoint: child.URL}
	source := &flipSource{ref: refStr, caps: []string{"openai.chat"}}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()

	// Raw TCP request: read one streamed chunk, then close the socket. The
	// gateway's next write detects the disconnect, cancels upstream and
	// releases the lease.
	conn, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	body := `{"model":"` + refStr + `","stream":true,"messages":[]}`
	_, _ = fmt.Fprintf(conn, "POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s", len(body), body)
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	buf := make([]byte, 4096)
	got := ""
	for !strings.Contains(got, "data:") {
		n, readErr := conn.Read(buf)
		if n > 0 {
			got += string(buf[:n])
		}
		if readErr != nil {
			_ = conn.Close()
			t.Fatalf("stream did not start: %v (%q)", readErr, got)
		}
	}
	_ = conn.Close()
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("child request was not cancelled")
	}
	deadline := time.Now().Add(5 * time.Second)
	for s.Scheduler.ActiveRequests(refStr) != 0 {
		if time.Now().After(deadline) {
			t.Fatalf("lease was not released: %d", s.Scheduler.ActiveRequests(refStr))
		}
		time.Sleep(20 * time.Millisecond)
	}
}

type flipPuller struct {
	source  *flipSource
	started chan struct{}
	release chan struct{}
	once    sync.Once
	calls   atomic.Int32
}

func (p *flipPuller) Pull(ctx context.Context, _ string, _ host.PullOptions) (host.PullResult, error) {
	p.calls.Add(1)
	if p.started != nil {
		p.once.Do(func() { close(p.started) })
	}
	select {
	case <-p.release:
	case <-ctx.Done():
		return host.PullResult{}, ctx.Err()
	}
	p.source.ready.Store(true)
	return host.PullResult{}, nil
}

func TestGatewayAutoPullThenRetry(t *testing.T) {
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chatcmpl-1","object":"chat.completion","model":"child","choices":[]}`)
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	source := &flipSource{ref: refStr, caps: []string{"openai.chat"}}
	launcher := &gatewayLauncher{endpoint: child.URL}
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))
	puller := &flipPuller{source: source, started: make(chan struct{}), release: make(chan struct{})}
	s.Puller = puller

	rec, body := call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("first request = %d: %s", rec.Code, rec.Body.String())
	}
	errBody, _ := body["error"].(map[string]any)
	if errBody["code"] != "model_preparing" {
		t.Fatalf("error = %v", body)
	}
	jobID, _ := errBody["job_id"].(string)
	if jobID == "" || rec.Header().Get("X-Flashcli-Preload-Job") != jobID {
		t.Fatalf("job header = %q body = %v", rec.Header().Get("X-Flashcli-Preload-Job"), body)
	}
	if rec.Header().Get("Retry-After") != "5" {
		t.Fatalf("Retry-After = %q", rec.Header().Get("Retry-After"))
	}
	<-puller.started
	close(puller.release)
	if state := waitJobState(t, s.Jobs, jobID); state != "done" {
		t.Fatalf("preload job = %s", state)
	}

	rec, body = call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("retry = %d: %s", rec.Code, rec.Body.String())
	}
	if puller.calls.Load() != 1 {
		t.Fatalf("puller calls = %d", puller.calls.Load())
	}
}

func TestGatewayValidationAndCapabilityErrors(t *testing.T) {
	refStr := "flashcli-bundle/demo:1.0.0"
	source := &flipSource{ref: refStr, caps: []string{"openai.embeddings"}}
	source.ready.Store(true)
	launcher := &gatewayLauncher{endpoint: "http://127.0.0.1:1"}
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))

	rec, body := call(t, s.Handler(), http.MethodPost, "/v1/chat/completions", `{"model":"demo:1","messages":[]}`)
	if rec.Code != http.StatusBadRequest || body["error"].(map[string]any)["code"] != "invalid_model" {
		t.Fatalf("short model = %d: %v", rec.Code, body)
	}

	rec, body = call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusBadRequest || body["error"].(map[string]any)["code"] != "unsupported_capability" {
		t.Fatalf("capability = %d: %v", rec.Code, body)
	}

	rec, body = call(t, s.Handler(), http.MethodPost, "/v1/messages",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusBadRequest || body["error"].(map[string]any)["code"] != "unsupported_capability" {
		t.Fatalf("anthropic capability = %d: %v", rec.Code, body)
	}

	rec, body = call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"flashcli-bundle/missing:1.0.0","messages":[]}`)
	if rec.Code != http.StatusServiceUnavailable || body["error"].(map[string]any)["code"] != "model_preparing" {
		t.Fatalf("unknown ref = %d: %v", rec.Code, body)
	}

	s.AutoPull = false
	s.Puller = nil
	rec, body = call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"flashcli-bundle/missing2:1.0.0","messages":[]}`)
	if rec.Code != http.StatusNotFound || body["error"].(map[string]any)["code"] != "model_not_found" {
		t.Fatalf("auto_pull off = %d: %v", rec.Code, body)
	}
}

func TestGatewayModelStartingReturnsRetryAfter(t *testing.T) {
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"id":"chatcmpl-1","object":"chat.completion","model":"child","choices":[]}`)
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	source := &flipSource{ref: refStr, caps: []string{"openai.chat"}}
	source.ready.Store(true)
	health := make(chan struct{})
	launcher := &gatewayLauncher{endpoint: child.URL, blockHealthy: health}
	s := gatewayTestServer(t, source, launcher, gatewayInspect(source.caps, gpuManifest(t)))
	s.ResidentStartWaitSeconds = 1

	rec, body := call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusServiceUnavailable || body["error"].(map[string]any)["code"] != "model_starting" {
		t.Fatalf("starting = %d: %s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Retry-After") != "2" {
		t.Fatalf("Retry-After = %q", rec.Header().Get("Retry-After"))
	}

	close(health)
	deadline := time.Now().Add(5 * time.Second)
	for {
		states := s.Scheduler.States()
		if info, ok := states[refStr]; ok && info.State == residentReady {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("resident did not become ready: %+v", states)
		}
		time.Sleep(20 * time.Millisecond)
	}

	rec, _ = call(t, s.Handler(), http.MethodPost, "/v1/chat/completions",
		`{"model":"`+refStr+`","messages":[]}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("retry after start = %d: %s", rec.Code, rec.Body.String())
	}
}

func multipartBody(t *testing.T, model, file string) ([]byte, string) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	if model != "" {
		if err := mw.WriteField("model", model); err != nil {
			t.Fatal(err)
		}
	}
	fw, err := mw.CreateFormFile("file", "a.wav")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := fw.Write([]byte(file)); err != nil {
		t.Fatal(err)
	}
	if err := mw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes(), mw.FormDataContentType()
}

func TestGatewayMultipartExtractsModelAndForwardsBody(t *testing.T) {
	var gotModel, gotFile string
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Errorf("child parse: %v", err)
			return
		}
		gotModel = r.FormValue("model")
		if f, _, err := r.FormFile("file"); err == nil {
			blob, _ := io.ReadAll(f)
			gotFile = string(blob)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","text":"ok"}`)
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	caps := []string{"openai.audio.transcriptions"}
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: child.URL}, gatewayInspect(caps, gpuManifest(t)))

	body, contentType := multipartBody(t, refStr, "audio-bytes")
	req := httptest.NewRequest(http.MethodPost, "/v1/audio/transcriptions", bytes.NewReader(body))
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("multipart = %d: %s", rec.Code, rec.Body.String())
	}
	if gotModel != refStr || gotFile != "audio-bytes" {
		t.Fatalf("child got model=%q file=%q", gotModel, gotFile)
	}
	if !strings.Contains(rec.Body.String(), `"model":"`+refStr+`"`) {
		t.Fatalf("model not rewritten: %s", rec.Body.String())
	}
}

func TestGatewayMultipartRequiresModelAndLimit(t *testing.T) {
	refStr := "flashcli-bundle/demo:1.0.0"
	caps := []string{"openai.audio.transcriptions"}
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: "http://127.0.0.1:1"}, gatewayInspect(caps, gpuManifest(t)))

	body, contentType := multipartBody(t, "", "audio")
	req := httptest.NewRequest(http.MethodPost, "/v1/audio/transcriptions", bytes.NewReader(body))
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest || !strings.Contains(rec.Body.String(), "model_required") {
		t.Fatalf("missing model = %d: %s", rec.Code, rec.Body.String())
	}

	s.MaxUploadBytes = 32
	body, contentType = multipartBody(t, refStr, strings.Repeat("x", 128))
	req = httptest.NewRequest(http.MethodPost, "/v1/audio/transcriptions", bytes.NewReader(body))
	req.Header.Set("Content-Type", contentType)
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("large upload = %d: %s", rec.Code, rec.Body.String())
	}
}

func TestGatewayRealtimeProxy(t *testing.T) {
	child := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close(websocket.StatusNormalClosure, "")
		for {
			typ, data, err := conn.Read(r.Context())
			if err != nil {
				return
			}
			if err := conn.Write(r.Context(), typ, append([]byte("echo:"), data...)); err != nil {
				return
			}
		}
	}))
	defer child.Close()

	refStr := "flashcli-bundle/demo:1.0.0"
	caps := []string{"openai.realtime"}
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: child.URL}, gatewayInspect(caps, gpuManifest(t)))
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/v1/realtime?model=" + url.QueryEscape(refStr)
	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := conn.Write(ctx, websocket.MessageText, []byte("hi")); err != nil {
		t.Fatal(err)
	}
	_, data, err := conn.Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "echo:hi" {
		t.Fatalf("echo = %q", data)
	}
	_ = conn.Close(websocket.StatusNormalClosure, "")

	deadline := time.Now().Add(5 * time.Second)
	for s.Scheduler.ActiveRequests(refStr) != 0 {
		if time.Now().After(deadline) {
			t.Fatalf("realtime lease was not released: %d", s.Scheduler.ActiveRequests(refStr))
		}
		time.Sleep(20 * time.Millisecond)
	}
}
