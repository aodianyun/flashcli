package server

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/host"
)

// gatewayChild records what the gateway forwarded and returns a JSON payload
// whose model must be rewritten by the gateway.
type gatewayChild struct {
	mu   sync.Mutex
	last recordedGatewayRequest
	srv  *httptest.Server
}

type recordedGatewayRequest struct {
	path        string
	contentType string
	body        string
}

func newGatewayChild(t *testing.T) *gatewayChild {
	t.Helper()
	c := &gatewayChild{}
	c.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blob, _ := io.ReadAll(r.Body)
		c.mu.Lock()
		c.last = recordedGatewayRequest{
			path: r.URL.Path, contentType: r.Header.Get("Content-Type"), body: string(blob),
		}
		c.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"id": "matrix", "object": "matrix", "model": "child", "path": r.URL.Path,
		})
	}))
	t.Cleanup(c.srv.Close)
	return c
}

func (c *gatewayChild) request() recordedGatewayRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.last
}

func postGateway(t *testing.T, s *Server, path, contentType string, body []byte) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(body))
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	return rec
}

func assertGatewayError(t *testing.T, rec *httptest.ResponseRecorder, wantStatus int, wantCode string) {
	t.Helper()
	if rec.Code != wantStatus {
		t.Fatalf("status = %d, want %d: %s", rec.Code, wantStatus, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid error body: %v (%s)", err, rec.Body.String())
	}
	errObj, _ := body["error"].(map[string]any)
	if errObj["code"] != wantCode {
		t.Fatalf("error = %v, want code %q", body["error"], wantCode)
	}
}

func TestGatewayJSONRouteMatrix(t *testing.T) {
	const refStr = "flashcli-bundle/demo:1.0.0"
	for path, route := range gatewayJSONRoutes {
		t.Run(path, func(t *testing.T) {
			child := newGatewayChild(t)
			source := &flipSource{ref: refStr, caps: []string{route.Capability}}
			source.ready.Store(true)
			s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: child.srv.URL},
				gatewayInspect(source.caps, gpuManifest(t)))

			body := []byte(`{"model":"` + refStr + `","input":"matrix","messages":[]}`)
			rec := postGateway(t, s, path, "application/json", body)
			if rec.Code != http.StatusOK {
				t.Fatalf("POST %s = %d: %s", path, rec.Code, rec.Body.String())
			}
			forwarded := child.request()
			if forwarded.path != route.Upstream {
				t.Fatalf("upstream path = %q, want %q", forwarded.path, route.Upstream)
			}
			if !strings.Contains(forwarded.body, refStr) {
				t.Fatalf("upstream body lost the model ref: %s", forwarded.body)
			}
			var reply map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &reply); err != nil {
				t.Fatalf("reply: %v (%s)", err, rec.Body.String())
			}
			if reply["model"] != refStr {
				t.Fatalf("reply model = %v, want %s", reply["model"], refStr)
			}

			// The same route must reject a model that does not declare its
			// capability.
			other := &flipSource{ref: refStr, caps: []string{"openai.other"}}
			other.ready.Store(true)
			denied := gatewayTestServer(t, other, &gatewayLauncher{endpoint: child.srv.URL},
				gatewayInspect(other.caps, gpuManifest(t)))
			rec = postGateway(t, denied, path, "application/json", body)
			assertGatewayError(t, rec, http.StatusBadRequest, "unsupported_capability")
		})
	}
}

func TestGatewayMultipartRouteMatrix(t *testing.T) {
	const refStr = "flashcli-bundle/demo:1.0.0"
	for path, route := range gatewayMultipartRoutes {
		t.Run(path, func(t *testing.T) {
			child := newGatewayChild(t)
			caps := []string{route.Capability}
			source := &flipSource{ref: refStr, caps: caps}
			source.ready.Store(true)
			s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: child.srv.URL},
				gatewayInspect(caps, gpuManifest(t)))

			body, contentType := multipartBody(t, refStr, "matrix-media")
			rec := postGateway(t, s, path, contentType, body)
			if rec.Code != http.StatusOK {
				t.Fatalf("POST %s = %d: %s", path, rec.Code, rec.Body.String())
			}
			forwarded := child.request()
			if forwarded.path != route.Upstream {
				t.Fatalf("upstream path = %q, want %q", forwarded.path, route.Upstream)
			}
			if !strings.Contains(forwarded.body, refStr) || !strings.Contains(forwarded.body, "matrix-media") {
				t.Fatalf("multipart body was not forwarded intact: %s", forwarded.body)
			}
			var reply map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &reply); err != nil {
				t.Fatalf("reply: %v (%s)", err, rec.Body.String())
			}
			if reply["model"] != refStr {
				t.Fatalf("reply model = %v, want %s", reply["model"], refStr)
			}

			// /v1/videos also accepts a JSON body.
			if path == "/v1/videos" {
				rec = postGateway(t, s, path, "application/json",
					[]byte(`{"model":"`+refStr+`","prompt":"matrix"}`))
				if rec.Code != http.StatusOK {
					t.Fatalf("JSON videos = %d: %s", rec.Code, rec.Body.String())
				}
				if got := child.request().path; got != route.Upstream {
					t.Fatalf("JSON upstream path = %q, want %q", got, route.Upstream)
				}
			}

			other := &flipSource{ref: refStr, caps: []string{"openai.other"}}
			other.ready.Store(true)
			denied := gatewayTestServer(t, other, &gatewayLauncher{endpoint: child.srv.URL},
				gatewayInspect(other.caps, gpuManifest(t)))
			body, contentType = multipartBody(t, refStr, "matrix-media")
			rec = postGateway(t, denied, path, contentType, body)
			assertGatewayError(t, rec, http.StatusBadRequest, "unsupported_capability")
		})
	}
}

// matrixSource lets the models endpoint see several refs with different
// readiness.
type matrixSource struct {
	models []host.Model
}

func (s matrixSource) Models(context.Context) ([]host.Model, error) { return s.models, nil }
func (s matrixSource) Storage(context.Context) ([]host.Area, error) { return nil, nil }

func TestGatewayModelsListsResidentAndPreloadedOnly(t *testing.T) {
	t.Setenv("FLASHCLI_HOME", t.TempDir())
	const resident = "flashcli-bundle/resident:1.0.0"
	const preloaded = "flashcli-bundle/preloaded:1.0.0"
	const unavailable = "flashcli-bundle/unavailable:1.0.0"
	source := matrixSource{models: []host.Model{
		{Ref: resident, CacheKey: "resident/1", BundleCached: true, WeightsCached: true, Serve: true, Capabilities: []string{"openai.chat"}},
		{Ref: preloaded, CacheKey: "preloaded/1", BundleCached: true, WeightsCached: true, Serve: true, Capabilities: []string{"openai.chat"}},
		{Ref: unavailable, CacheKey: "unavailable/1", BundleCached: true, WeightsCached: false, Serve: true},
	}}
	inspect := gatewayInspect([]string{"openai.chat"}, gpuManifest(t))
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: "http://127.0.0.1:1"}, inspect)
	s.preloads().setState(preloaded, preloadReady, "")

	lease, err := s.Scheduler.Acquire(context.Background(), resident)
	if err != nil {
		t.Fatal(err)
	}
	lease.Release()

	rec, body := call(t, s.Handler(), http.MethodGet, "/v1/models", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("models = %d: %s", rec.Code, rec.Body.String())
	}
	data, _ := body["data"].([]any)
	if len(data) != 2 {
		t.Fatalf("models = %v, want resident+preloaded only", body["data"])
	}
	// The response is sorted by id.
	first, _ := data[0].(map[string]any)
	second, _ := data[1].(map[string]any)
	if first["id"] != preloaded || second["id"] != resident {
		t.Fatalf("models = %v, want sorted %s, %s", body["data"], preloaded, resident)
	}
	if caps, _ := second["capabilities"].([]any); len(caps) != 1 || caps[0] != "openai.chat" {
		t.Fatalf("resident capabilities = %v", second["capabilities"])
	}
	for _, item := range data {
		if m, _ := item.(map[string]any); m["id"] == unavailable {
			t.Fatalf("unavailable model was listed: %v", body["data"])
		}
	}
}

func TestGatewayMultipartRejectsInvalidContentType(t *testing.T) {
	const refStr = "flashcli-bundle/demo:1.0.0"
	caps := []string{"openai.audio.transcriptions"}
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: "http://127.0.0.1:1"},
		gatewayInspect(caps, gpuManifest(t)))

	rec := postGateway(t, s, "/v1/audio/transcriptions", "application/octet-stream", []byte("not multipart"))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_multipart")

	body, contentType := multipartBody(t, "", "media")
	rec = postGateway(t, s, "/v1/audio/transcriptions", contentType, body)
	assertGatewayError(t, rec, http.StatusBadRequest, "model_required")

	body, contentType = multipartBody(t, "short:1", "media")
	rec = postGateway(t, s, "/v1/audio/transcriptions", contentType, body)
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_model")
}

func TestGatewayJSONValidationIncludesOversizeBody(t *testing.T) {
	const refStr = "flashcli-bundle/demo:1.0.0"
	caps := []string{"openai.chat"}
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	s := gatewayTestServer(t, source, &gatewayLauncher{endpoint: "http://127.0.0.1:1"},
		gatewayInspect(caps, gpuManifest(t)))

	rec := postGateway(t, s, "/v1/chat/completions", "application/json", []byte(`{"model":`))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_json")

	rec = postGateway(t, s, "/v1/chat/completions", "application/json", []byte(`{}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "model_required")

	rec = postGateway(t, s, "/v1/chat/completions", "application/json", []byte(`{"model":"demo:1"}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_model")

	oversize := append([]byte(`{"model":"`+refStr+`","input":"`), bytes.Repeat([]byte("x"), gatewayMaxBody)...)
	oversize = append(oversize, []byte(`"}`)...)
	rec = postGateway(t, s, "/v1/chat/completions", "application/json", oversize)
	assertGatewayError(t, rec, http.StatusRequestEntityTooLarge, "request_too_large")
}
