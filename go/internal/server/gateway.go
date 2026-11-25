package server

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/ref"
)

// OpenAIModel is one entry in an OpenAI `GET /v1/models` response.
type OpenAIModel struct {
	ID           string   `json:"id"`
	Object       string   `json:"object"`
	Created      int64    `json:"created"`
	OwnedBy      string   `json:"owned_by"`
	Capabilities []string `json:"capabilities,omitempty"`
}

// gatewayMaxBody bounds JSON request bodies. Multipart/WebSocket limits arrive
// with their routes in the next milestone.
const gatewayMaxBody = 32 << 20

// gatewayRoutes maps public gateway paths to the child serve route and the
// bundle capability that must be declared.
var gatewayRoutes = map[string]struct {
	Capability string
	Upstream   string
}{
	"/v1/chat/completions": {"openai.chat", "/v1/chat/completions"},
	"/v1/completions":      {"openai.completions", "/v1/completions"},
	"/v1/responses":        {"openai.responses", "/v1/responses"},
	"/v1/embeddings":       {"openai.embeddings", "/v1/embeddings"},
	"/v1/moderations":      {"openai.moderations", "/v1/moderations"},
}

// gatewayHandler builds the handler for one gateway route.
func (s *Server) gatewayHandler(capability, upstream string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.serveGateway(w, r, capability, upstream)
	}
}

// gatewayModels serves GET /v1/models for the OpenAI gateway. It lists the
// models whose assets are locally available (preloaded or resident), using the
// OpenAI list shape. FlashHub catalog browsing stays on the management API
// (/api/v1/catalog).
func (s *Server) gatewayModels(w http.ResponseWriter, r *http.Request) {
	now := time.Now().Unix()
	seen := map[string]bool{}
	data := make([]OpenAIModel, 0)
	add := func(id string, created int64, capabilities []string) {
		if id == "" || seen[id] {
			return
		}
		seen[id] = true
		if created == 0 {
			created = now
		}
		data = append(data, OpenAIModel{
			ID: id, Object: "model", Created: created, OwnedBy: "flashcli",
			Capabilities: append([]string(nil), capabilities...),
		})
	}

	if s.Manager != nil {
		for _, inst := range s.Manager.List() {
			add(inst.Ref, inst.LoadedAt.Unix(), inst.Capabilities)
		}
	}
	states := s.preloads().snapshot()
	if s.Source != nil {
		if models, err := s.Source.Models(r.Context()); err == nil {
			for _, m := range models {
				state := ""
				if e, ok := states[m.Ref]; ok {
					state = e.State
				}
				if !preloadedAssets(m) && state != preloadReady {
					continue
				}
				add(m.Ref, 0, m.Capabilities)
			}
		}
	}
	// An explicit preload can succeed before the cache walker sees the marker
	// (and tests use a fake puller); report the recorded intent too.
	for refStr, e := range states {
		if e.State == preloadReady {
			add(refStr, 0, nil)
		}
	}
	sort.Slice(data, func(i, j int) bool { return data[i].ID < data[j].ID })
	writeJSON(w, http.StatusOK, map[string]any{"object": "list", "data": data})
}

// inspectRef resolves bundle admission metadata through the scheduler's
// injectable inspector (tests) or the real host inspector.
func (s *Server) inspectRef(refStr string) (BundleInfo, error) {
	if s.Scheduler != nil && s.Scheduler.opts.Inspect != nil {
		return s.Scheduler.opts.Inspect(refStr)
	}
	return inspectBundle(refStr)
}

// serveGateway validates and proxies one JSON inference request.
func (s *Server) serveGateway(w http.ResponseWriter, r *http.Request, capability, upstreamPath string) {
	body, err := io.ReadAll(io.LimitReader(r.Body, gatewayMaxBody+1))
	if err != nil {
		writeGatewayError(w, http.StatusBadRequest, "invalid_request_error", "invalid_request_error", "cannot read request body", "", "", 0)
		return
	}
	if len(body) > gatewayMaxBody {
		writeGatewayError(w, http.StatusRequestEntityTooLarge, "request_too_large", "invalid_request_error", "request body is too large", "", "", 0)
		return
	}
	var parsed struct {
		Model  string `json:"model"`
		Stream bool   `json:"stream"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		writeGatewayError(w, http.StatusBadRequest, "invalid_json", "invalid_request_error", "request body must be valid JSON", "", "", 0)
		return
	}
	refStr := strings.TrimSpace(parsed.Model)
	if refStr == "" {
		writeGatewayError(w, http.StatusBadRequest, "model_required", "invalid_request_error", "model is required", "", "", 0)
		return
	}
	if !ref.IsFlashHub(refStr) {
		writeGatewayError(w, http.StatusBadRequest, "invalid_model", "invalid_request_error",
			"model must be a full bundle ref (namespace/name:version)", refStr, "", 0)
		return
	}

	// Auto-pull gate: do not start a job (or require a Puller) when the
	// operator disabled auto-pull and the model is absent.
	if !s.assetsReady(r.Context(), refStr) && s.preloads().state(refStr) != preloadReady && !s.AutoPull {
		writeGatewayError(w, http.StatusNotFound, "model_not_found", "invalid_request_error",
			"model is not preloaded and auto_pull is disabled", refStr, "", 0)
		return
	}

	ready, jobID, err := s.ensurePreload(r.Context(), refStr)
	if err != nil {
		writeGatewayError(w, http.StatusServiceUnavailable, "model_preparing", "server_busy", err.Error(), refStr, "", 5)
		return
	}
	if !ready {
		retry := s.preloadRetryAfter(jobID)
		writeGatewayError(w, http.StatusServiceUnavailable, "model_preparing", "server_busy",
			"model is being preloaded", refStr, jobID, retry)
		return
	}

	info, err := s.inspectRef(refStr)
	if err != nil {
		writeGatewayError(w, http.StatusNotFound, "model_not_found", "invalid_request_error",
			"model is not available: "+err.Error(), refStr, "", 0)
		return
	}
	if info.RunOnly {
		writeGatewayError(w, http.StatusBadRequest, "model_not_servable", "invalid_request_error",
			"bundle has no serve entry", refStr, "", 0)
		return
	}
	if !hasCapability(info.Capabilities, capability) {
		writeGatewayError(w, http.StatusBadRequest, "unsupported_capability", "invalid_request_error",
			fmt.Sprintf("model does not declare %s", capability), refStr, "", 0)
		return
	}
	if s.Scheduler == nil {
		writeGatewayError(w, http.StatusServiceUnavailable, "no_placement", "server_error",
			"scheduler is not configured", refStr, "", 0)
		return
	}

	lease, gerr := s.acquireForRequest(r.Context(), refStr)
	if gerr != nil {
		gerr.write(w)
		return
	}
	defer lease.Release()

	endpoint, ok := s.Manager.Endpoint(refStr)
	if !ok {
		writeGatewayError(w, http.StatusServiceUnavailable, "model_starting", "server_busy",
			"model endpoint is not ready", refStr, "", 2)
		return
	}
	s.proxyGateway(w, r, endpoint, upstreamPath, refStr, body, parsed.Stream)
}

// gatewayFailure is a mapped gateway error.
type gatewayFailure struct {
	Status  int
	Code    string
	Type    string
	Message string
	Ref     string
	Retry   int
}

func (e *gatewayFailure) write(w http.ResponseWriter) {
	writeGatewayError(w, e.Status, e.Code, e.Type, e.Message, e.Ref, "", e.Retry)
}

// acquireForRequest waits for a resident according to resident_start_wait and
// the queue timeout, then maps scheduler failures to OpenAI-style errors.
func (s *Server) acquireForRequest(ctx context.Context, refStr string) (*Lease, *gatewayFailure) {
	startWait := s.ResidentStartWaitSeconds
	if startWait <= 0 {
		startWait = 10
	}
	queueWait := s.QueueTimeoutSeconds
	if queueWait < 0 {
		queueWait = 0
	}
	wait := time.Duration(startWait+queueWait+1) * time.Second
	waitCtx, cancel := context.WithTimeout(ctx, wait)
	defer cancel()

	lease, err := s.Scheduler.Acquire(waitCtx, refStr)
	if err == nil {
		return lease, nil
	}
	if ctx.Err() != nil {
		return nil, &gatewayFailure{Status: 499, Code: "client_closed", Type: "invalid_request_error", Message: "client closed the request"}
	}
	var pe *PlacementError
	if errors.As(err, &pe) {
		switch pe.Code {
		case "queue_full":
			return nil, &gatewayFailure{Status: http.StatusTooManyRequests, Code: "queue_full", Type: "server_busy",
				Message: "the model queue is full", Ref: refStr, Retry: 5}
		default:
			retry := 0
			if pe.Reason == reasonResourceExhausted {
				retry = 5
			}
			msg := "no placement is currently available"
			if pe.Reason != "" {
				msg += ": " + pe.Reason
			}
			return nil, &gatewayFailure{Status: http.StatusServiceUnavailable, Code: "no_placement", Type: "server_error",
				Message: msg, Ref: refStr, Retry: retry}
		}
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		if s.Scheduler.Resident(refStr) {
			return nil, &gatewayFailure{Status: http.StatusServiceUnavailable, Code: "model_starting", Type: "server_busy",
				Message: "model is starting", Ref: refStr, Retry: 2}
		}
		return nil, &gatewayFailure{Status: http.StatusServiceUnavailable, Code: "no_placement", Type: "server_error",
			Message: "model is waiting for resources", Ref: refStr, Retry: 5}
	}
	return nil, &gatewayFailure{Status: http.StatusBadGateway, Code: "model_start_failed", Type: "server_error",
		Message: err.Error(), Ref: refStr}
}

// proxyGateway forwards the request to the child serve endpoint and streams the
// response. The child endpoint is never exposed to the caller.
func (s *Server) proxyGateway(w http.ResponseWriter, r *http.Request, endpoint, upstreamPath, refStr string, body []byte, stream bool) {
	target := strings.TrimRight(endpoint, "/") + upstreamPath
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	if cn, ok := w.(http.CloseNotifier); ok {
		go func() {
			select {
			case <-cn.CloseNotify():
				cancel()
			case <-ctx.Done():
			}
		}()
	}
	up, err := http.NewRequestWithContext(ctx, http.MethodPost, target, bytes.NewReader(body))
	if err != nil {
		writeGatewayError(w, http.StatusInternalServerError, "proxy_error", "server_error", err.Error(), refStr, "", 0)
		return
	}
	for _, name := range []string{"Content-Type", "Accept", "OpenAI-Organization", "OpenAI-Project", "Anthropic-Version"} {
		if v := r.Header.Get(name); v != "" {
			up.Header.Set(name, v)
		}
	}
	if up.Header.Get("Content-Type") == "" {
		up.Header.Set("Content-Type", "application/json")
	}
	client := &http.Client{}
	resp, err := client.Do(up)
	if err != nil {
		if r.Context().Err() != nil {
			return
		}
		writeGatewayError(w, http.StatusBadGateway, "proxy_error", "server_error", err.Error(), refStr, "", 0)
		return
	}
	defer resp.Body.Close()
	copyGatewayHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)

	contentType := resp.Header.Get("Content-Type")
	flusher, _ := w.(http.Flusher)
	switch {
	case strings.Contains(contentType, "text/event-stream"):
		rewriteSSEModel(resp.Body, w, refStr, flusher)
	case strings.Contains(contentType, "application/json"):
		rewriteJSONModel(resp.Body, w, refStr)
	default:
		_, _ = io.Copy(w, resp.Body)
	}
}

func (s *Server) preloadRetryAfter(jobID string) int {
	if s.Jobs == nil || jobID == "" {
		return 5
	}
	j, ok := s.Jobs.Get(jobID)
	if !ok {
		return 5
	}
	j.mu.Lock()
	started := j.StartedAt
	state := j.State
	events := append([]Event(nil), j.Events...)
	j.mu.Unlock()
	if state == "failed" {
		return 0
	}
	age := time.Since(started)
	if age < 0 {
		age = 0
	}
	if pct, ok := lastProgressPercent(events); ok && pct > 0 && pct < 100 {
		eta := age.Seconds() * (100 - pct) / pct
		return clampInt(int(math.Ceil(eta)), 5, 60)
	}
	switch {
	case age < time.Minute:
		return 5
	case age < 5*time.Minute:
		return 15
	case age < 15*time.Minute:
		return 30
	default:
		return 60
	}
}

func lastProgressPercent(events []Event) (float64, bool) {
	for i := len(events) - 1; i >= 0; i-- {
		msg := events[i].Message
		idx := strings.LastIndex(msg, "%")
		if idx <= 0 {
			continue
		}
		start := idx - 1
		for start >= 0 && (msg[start] >= '0' && msg[start] <= '9' || msg[start] == '.') {
			start--
		}
		v, err := strconv.ParseFloat(msg[start+1:idx], 64)
		if err == nil {
			return v, true
		}
	}
	return 0, false
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func hasCapability(capabilities []string, want string) bool {
	for _, cap := range capabilities {
		if cap == want {
			return true
		}
	}
	return false
}

func writeGatewayError(w http.ResponseWriter, status int, code, typ, message, model, jobID string, retry int) {
	if retry > 0 {
		w.Header().Set("Retry-After", strconv.Itoa(retry))
	}
	if jobID != "" {
		w.Header().Set("X-Flashcli-Preload-Job", jobID)
	}
	errObj := map[string]any{"message": message, "type": typ, "code": code}
	if model != "" {
		errObj["model"] = model
	}
	if jobID != "" {
		errObj["job_id"] = jobID
	}
	writeJSON(w, status, map[string]any{"error": errObj})
}

func copyGatewayHeaders(dst, src http.Header) {
	for name, values := range src {
		switch strings.ToLower(name) {
		case "connection", "transfer-encoding", "content-length", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade":
			continue
		}
		for _, v := range values {
			dst.Add(name, v)
		}
	}
}

func rewriteJSONModel(src io.Reader, w io.Writer, refStr string) {
	blob, err := io.ReadAll(io.LimitReader(src, gatewayMaxBody))
	if err != nil {
		return
	}
	if out, ok := rewriteModelBlob(blob, refStr); ok {
		_, _ = w.Write(out)
		return
	}
	_, _ = w.Write(blob)
}

func rewriteModelBlob(blob []byte, refStr string) ([]byte, bool) {
	var v map[string]any
	if err := json.Unmarshal(blob, &v); err != nil {
		return nil, false
	}
	if _, ok := v["model"]; !ok {
		return nil, false
	}
	v["model"] = refStr
	out, err := json.Marshal(v)
	if err != nil {
		return nil, false
	}
	return out, true
}

func rewriteSSEModel(src io.Reader, w io.Writer, refStr string, flusher http.Flusher) {
	scanner := bufio.NewScanner(src)
	scanner.Buffer(make([]byte, 64*1024), gatewayMaxBody)
	for scanner.Scan() {
		line := strings.TrimSuffix(scanner.Text(), "\r")
		if strings.HasPrefix(line, "data:") {
			payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if payload != "" && payload != "[DONE]" {
				if out, ok := rewriteModelBlob([]byte(payload), refStr); ok {
					line = "data: " + string(out)
				}
			}
		}
		if _, err := io.WriteString(w, line+"\n"); err != nil {
			return
		}
		if line == "" && flusher != nil {
			flusher.Flush()
		}
	}
}
