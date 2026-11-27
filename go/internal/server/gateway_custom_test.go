package server

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
)

type customChild struct {
	mu          sync.Mutex
	method      string
	path        string
	rawQuery    string
	contentType string
	header      http.Header
	body        []byte
	calls       int
}

func newCustomGatewayChild(t *testing.T, reply http.HandlerFunc) (*httptest.Server, *customChild) {
	t.Helper()
	c := &customChild{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blob, _ := io.ReadAll(r.Body)
		c.mu.Lock()
		c.calls++
		c.method = r.Method
		c.path = r.URL.Path
		c.rawQuery = r.URL.RawQuery
		c.contentType = r.Header.Get("Content-Type")
		c.header = r.Header.Clone()
		c.body = blob
		c.mu.Unlock()
		reply(w, r)
	}))
	t.Cleanup(srv.Close)
	return srv, c
}

func (c *customChild) snapshot() (method, path, rawQuery, contentType string, header http.Header, body []byte, calls int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.method, c.path, c.rawQuery, c.contentType, c.header.Clone(), append([]byte(nil), c.body...), c.calls
}

func customGatewayServer(t *testing.T, endpoint string, caps []string) *Server {
	t.Helper()
	const refStr = "flashcli-bundle/demo:1.0.0"
	source := &flipSource{ref: refStr, caps: caps}
	source.ready.Store(true)
	return gatewayTestServer(t, source, &gatewayLauncher{endpoint: endpoint}, gatewayInspect(caps, gpuManifest(t)))
}

func TestGatewayCustomJSONPathUsesBodyModel(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","text":"ok"}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	req := httptest.NewRequest(http.MethodPost, "/v1/ocr/batch?trace=1",
		strings.NewReader(`{"model":"`+refStr+`","inputs":["a"]}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("custom JSON = %d: %s", rec.Code, rec.Body.String())
	}
	method, path, rawQuery, _, _, body, _ := recorded.snapshot()
	if method != http.MethodPost || path != "/v1/ocr/batch" || rawQuery != "trace=1" {
		t.Fatalf("forwarded %s %s?%s", method, path, rawQuery)
	}
	if !strings.Contains(string(body), refStr) {
		t.Fatalf("body lost the model: %s", body)
	}
	var reply map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &reply); err != nil {
		t.Fatal(err)
	}
	if reply["model"] != refStr {
		t.Fatalf("response model = %v", reply["model"])
	}
	if got := s.Scheduler.ActiveRequests(refStr); got != 0 {
		t.Fatalf("lease leaked: %d", got)
	}
}

func TestGatewayCustomQueryModelIsStripped(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","spec_version":"2026-11-26"}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	req := httptest.NewRequest(http.MethodGet,
		"/v1/audio/spec?model="+url.QueryEscape(refStr)+"&lang=zh", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("custom GET = %d: %s", rec.Code, rec.Body.String())
	}
	method, path, rawQuery, _, _, body, _ := recorded.snapshot()
	if method != http.MethodGet || path != "/v1/audio/spec" || rawQuery != "lang=zh" {
		t.Fatalf("forwarded %s %s?%s", method, path, rawQuery)
	}
	if len(body) != 0 {
		t.Fatalf("GET body = %q", body)
	}
	if !strings.Contains(rec.Body.String(), `"model":"`+refStr+`"`) {
		t.Fatalf("response model not rewritten: %s", rec.Body.String())
	}
}

func TestGatewayCustomMultipartPath(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","tracks":[]}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	body, contentType := multipartBody(t, refStr, "media-bytes")
	req := httptest.NewRequest(http.MethodPost, "/v1/audio/separations", bytes.NewReader(body))
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("custom multipart = %d: %s", rec.Code, rec.Body.String())
	}
	_, path, _, gotType, _, gotBody, _ := recorded.snapshot()
	if path != "/v1/audio/separations" {
		t.Fatalf("upstream path = %q", path)
	}
	if !strings.HasPrefix(gotType, "multipart/form-data") {
		t.Fatalf("upstream content type = %q", gotType)
	}
	if !strings.Contains(string(gotBody), refStr) || !strings.Contains(string(gotBody), "media-bytes") {
		t.Fatalf("multipart body was not forwarded intact")
	}
}

func TestGatewayCustomPathSkipsCapabilityGate(t *testing.T) {
	child, _ := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","ok":true}`)
	})
	// The model only declares openai.chat, but /v1/ocr is a bundle-owned
	// custom route and is not capability-gated.
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	rec := postGateway(t, s, "/v1/ocr", "application/json",
		[]byte(`{"model":"`+refStr+`","image":"x"}`))
	if rec.Code != http.StatusOK {
		t.Fatalf("custom path = %d: %s", rec.Code, rec.Body.String())
	}
}

func TestGatewayCustomModelSelectionErrors(t *testing.T) {
	const refStr = "flashcli-bundle/demo:1.0.0"
	s := customGatewayServer(t, "http://127.0.0.1:1", []string{"openai.chat"})

	rec := postGateway(t, s, "/v1/ocr", "application/json", []byte(`{}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "model_required")

	rec = postGateway(t, s, "/v1/ocr?model="+url.QueryEscape(refStr), "application/json",
		[]byte(`{"model":"flashcli-bundle/other:1.0.0"}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "model_conflict")

	rec = postGateway(t, s, "/v1/ocr", "application/json", []byte(`{"model":"demo:1"}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_model")

	req := httptest.NewRequest(http.MethodGet, "/v1/audio/spec", nil)
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	assertGatewayError(t, rec, http.StatusBadRequest, "model_required")
}

func TestGatewayCustomNonObjectJSONBodyUsesQueryModel(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok":true}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	body := `[{"image":"a"},{"image":"b"}]`
	req := httptest.NewRequest(http.MethodPost, "/v1/ocr/batch?model="+url.QueryEscape(refStr),
		strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("array JSON = %d: %s", rec.Code, rec.Body.String())
	}
	_, _, _, _, _, gotBody, _ := recorded.snapshot()
	if string(gotBody) != body {
		t.Fatalf("array body changed: %s", gotBody)
	}

	rec = postGateway(t, s, "/v1/ocr", "application/json", []byte(`{`))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_json")

	rec = postGateway(t, s, "/v1/ocr", "application/json", []byte(`{"model":123}`))
	assertGatewayError(t, rec, http.StatusBadRequest, "invalid_model")
}

func TestGatewayCustomEmptyJSONBodyUsesQueryModel(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","ok":true}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	req := httptest.NewRequest(http.MethodPost, "/v1/ocr?model="+url.QueryEscape(refStr), nil)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("empty custom JSON = %d: %s", rec.Code, rec.Body.String())
	}
	_, path, rawQuery, _, _, body, _ := recorded.snapshot()
	if path != "/v1/ocr" || rawQuery != "" || len(body) != 0 {
		t.Fatalf("forwarded %s?%s body=%q", path, rawQuery, body)
	}
}

func TestGatewayCustomPathStripsCredentialsAndForwardsHeaders(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","ok":true}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	s.Token = "secret"
	const refStr = "flashcli-bundle/demo:1.0.0"

	req := httptest.NewRequest(http.MethodGet,
		"/v1/audio/spec?model="+url.QueryEscape(refStr), nil)
	req.Header.Set("Authorization", "Bearer secret")
	req.Header.Set("X-Flashcli-Token", "secret")
	req.Header.Set("Cookie", "session=1")
	req.Header.Set("X-Trace", "abc")
	req.Header.Set("Range", "bytes=0-10")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("custom GET = %d: %s", rec.Code, rec.Body.String())
	}
	_, _, _, _, header, _, _ := recorded.snapshot()
	if header.Get("Authorization") != "" || header.Get("X-Flashcli-Token") != "" || header.Get("Cookie") != "" {
		t.Fatalf("gateway credentials leaked: %v", header)
	}
	if header.Get("X-Trace") != "abc" || header.Get("Range") != "bytes=0-10" {
		t.Fatalf("custom headers not forwarded: %v", header)
	}
}

func TestGatewayCustomWebSocketRejected(t *testing.T) {
	s := customGatewayServer(t, "http://127.0.0.1:1", []string{"openai.chat"})
	req := httptest.NewRequest(http.MethodGet, "/v1/ocr/stream", nil)
	req.Header.Set("Upgrade", "websocket")
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	assertGatewayError(t, rec, http.StatusNotImplemented, "custom_websocket_unsupported")
}

func TestGatewayReservedPathsKeepMethodSemantics(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child"}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})

	cases := []struct {
		method string
		path   string
		allow  string
	}{
		{http.MethodPost, "/v1/models", "GET, HEAD"},
		{http.MethodGet, "/v1/chat/completions", "POST"},
		{http.MethodPost, "/v1/videos/abc", "GET, HEAD, DELETE"},
		{http.MethodPost, "/v1/videos/abc/content", "GET, HEAD"},
		{http.MethodGet, "/v1/responses/abc/cancel", "POST"},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		assertGatewayError(t, rec, http.StatusMethodNotAllowed, "method_not_allowed")
		if got := rec.Header().Get("Allow"); got != tc.allow {
			t.Fatalf("%s %s Allow = %q, want %q", tc.method, tc.path, got, tc.allow)
		}
	}

	// Reserved namespaces with no matching standard route are 404, never
	// forwarded as custom paths.
	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/v1/videos/abc/content/extra"},
		{http.MethodPost, "/v1/chat/completions/"},
		{http.MethodGet, "/v1/videos/"},
	} {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		assertGatewayError(t, rec, http.StatusNotFound, "not_found")
	}

	_, _, _, _, _, _, calls := recorded.snapshot()
	if calls != 0 {
		t.Fatalf("reserved paths reached the child %d times", calls)
	}
}

func TestGatewayModelsDetailOpenAIAndAnthropic(t *testing.T) {
	s := customGatewayServer(t, "http://127.0.0.1:1", []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	req := httptest.NewRequest(http.MethodGet, "/v1/models/"+refStr, nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("model detail = %d: %s", rec.Code, rec.Body.String())
	}
	var got map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["id"] != refStr || got["object"] != "model" {
		t.Fatalf("model detail = %v", got)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/models/"+refStr, nil)
	req.Header.Set("anthropic-version", "2023-06-01")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("anthropic model detail = %d: %s", rec.Code, rec.Body.String())
	}
	got = nil
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["type"] != "model" || got["id"] != refStr || got["display_name"] != refStr {
		t.Fatalf("anthropic model detail = %v", got)
	}

	// OpenAI SDKs may URL-escape the full ref as one path segment.
	req = httptest.NewRequest(http.MethodGet, "/v1/models/"+url.PathEscape(refStr), nil)
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("escaped model detail = %d: %s", rec.Code, rec.Body.String())
	}

	// The Anthropic list shape is selected by the version header.
	req = httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	req.Header.Set("anthropic-version", "2023-06-01")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("anthropic model list = %d: %s", rec.Code, rec.Body.String())
	}
	var list map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &list); err != nil {
		t.Fatal(err)
	}
	items, _ := list["data"].([]any)
	if len(items) != 1 {
		t.Fatalf("anthropic model list = %v", list)
	}
	first, _ := items[0].(map[string]any)
	if first["type"] != "model" || first["id"] != refStr {
		t.Fatalf("anthropic model list item = %v", first)
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/models?limit=0", nil)
	req.Header.Set("anthropic-version", "2023-06-01")
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("invalid anthropic limit = %d: %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodGet, "/v1/models/flashcli-bundle/missing:1.0.0", nil)
	rec = httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	assertGatewayError(t, rec, http.StatusNotFound, "model_not_found")
}

func TestGatewayResponseSubroutes(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","id":"resp_1","object":"response"}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.responses"})
	const refStr = "flashcli-bundle/demo:1.0.0"
	modelQuery := "?model=" + url.QueryEscape(refStr)

	cases := []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/v1/responses/resp_1"},
		{http.MethodDelete, "/v1/responses/resp_1"},
		{http.MethodPost, "/v1/responses/resp_1/cancel"},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(tc.method, tc.path+modelQuery, nil)
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s %s = %d: %s", tc.method, tc.path, rec.Code, rec.Body.String())
		}
		method, path, _, _, _, _, _ := recorded.snapshot()
		if method != tc.method || path != tc.path {
			t.Fatalf("forwarded %s %s, want %s %s", method, path, tc.method, tc.path)
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/responses/resp_1", nil)
	rec := httptest.NewRecorder()
	s.Handler().ServeHTTP(rec, req)
	assertGatewayError(t, rec, http.StatusBadRequest, "model_required")
}

func TestGatewayVideoJobRoutes(t *testing.T) {
	child, recorded := newCustomGatewayChild(t, func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/content") {
			w.Header().Set("Content-Type", "video/mp4")
			_, _ = io.WriteString(w, "video-bytes")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":"child","object":"list","data":[]}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.videos"})
	const refStr = "flashcli-bundle/demo:1.0.0"
	modelQuery := "?model=" + url.QueryEscape(refStr)

	cases := []struct {
		method string
		path   string
		query  string
	}{
		{http.MethodGet, "/v1/videos", modelQuery + "&limit=5"},
		{http.MethodGet, "/v1/videos/v1", modelQuery},
		{http.MethodDelete, "/v1/videos/v1", modelQuery},
		{http.MethodGet, "/v1/videos/v1/content", modelQuery},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(tc.method, tc.path+tc.query, nil)
		rec := httptest.NewRecorder()
		s.Handler().ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s %s = %d: %s", tc.method, tc.path, rec.Code, rec.Body.String())
		}
		method, path, rawQuery, _, _, _, _ := recorded.snapshot()
		if method != tc.method || path != tc.path {
			t.Fatalf("forwarded %s %s, want %s %s", method, path, tc.method, tc.path)
		}
		wantQuery := strings.TrimPrefix(tc.query, "?model="+url.QueryEscape(refStr))
		wantQuery = strings.TrimPrefix(wantQuery, "&")
		if rawQuery != wantQuery {
			t.Fatalf("%s %s query = %q, want %q", tc.method, tc.path, rawQuery, wantQuery)
		}
	}
}

func TestRewriteJSONModelStreamsLargePayload(t *testing.T) {
	size := int64(gatewayMaxBody) + 1024
	var out bytes.Buffer
	rewriteJSONModel(&repeatReader{remaining: size}, &out, "flashcli-bundle/demo:1.0.0", false, -1)
	if int64(out.Len()) != size {
		t.Fatalf("streamed %d bytes, want %d", out.Len(), size)
	}

	// A declared large body is streamed without buffering or rewriting.
	out.Reset()
	rewriteJSONModel(strings.NewReader(`{"model":"child"}`), &out, "flashcli-bundle/demo:1.0.0", false, int64(gatewayMaxBody)+1)
	if out.String() != `{"model":"child"}` {
		t.Fatalf("large known body was modified: %s", out.String())
	}
}

type repeatReader struct {
	remaining int64
}

func (r *repeatReader) Read(p []byte) (int, error) {
	if r.remaining <= 0 {
		return 0, io.EOF
	}
	n := len(p)
	if int64(n) > r.remaining {
		n = int(r.remaining)
	}
	for i := 0; i < n; i++ {
		p[i] = 'x'
	}
	r.remaining -= int64(n)
	return n, nil
}

func TestGatewayModelRewriteIgnoresNonStringModel(t *testing.T) {
	child, _ := newCustomGatewayChild(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"model":{"name":"child"},"ok":true}`)
	})
	s := customGatewayServer(t, child.URL, []string{"openai.chat"})
	const refStr = "flashcli-bundle/demo:1.0.0"

	rec := postGateway(t, s, "/v1/chat/completions", "application/json",
		[]byte(`{"model":"`+refStr+`","messages":[]}`))
	if rec.Code != http.StatusOK {
		t.Fatalf("chat = %d: %s", rec.Code, rec.Body.String())
	}
	var reply map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &reply); err != nil {
		t.Fatal(err)
	}
	model, _ := reply["model"].(map[string]any)
	if model["name"] != "child" {
		t.Fatalf("structured model field was rewritten: %v", reply)
	}
}

func TestStripGatewayModelQuery(t *testing.T) {
	got := stripGatewayModelQuery("model=a%2Fb%3A1&x=1&x=2&y=%E4%B8%AD&model=other")
	want := "x=1&x=2&y=%E4%B8%AD"
	if got != want {
		t.Fatalf("stripped query = %q, want %q", got, want)
	}
}
