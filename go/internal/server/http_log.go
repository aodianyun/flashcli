package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	httpLogBodyLimit = 2048
	httpLogRespLimit = 1024
)

// statusRecorder captures the status code, size and (for errors) the beginning
// of the response body without changing the handler behavior.
type statusRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
	body   bytes.Buffer
}

func (r *statusRecorder) WriteHeader(code int) {
	if r.status == 0 {
		r.status = code
	}
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(p []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	n, err := r.ResponseWriter.Write(p)
	r.bytes += n
	if r.body.Len() < httpLogRespLimit {
		room := httpLogRespLimit - r.body.Len()
		if room > len(p) {
			room = len(p)
		}
		r.body.Write(p[:room])
	}
	return n, err
}

// Flush keeps SSE endpoints (`/v1/jobs/{id}/events`, `/v1/ui/chat`) working
// through the logging wrapper.
func (r *statusRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

// logRequests writes every API call (except the high-frequency health check,
// WebSocket stream and static UI assets) into the service log, together with
// the status, duration and a redacted request body. Error responses include a
// truncated body. Job events add the intermediate operation steps.
func (s *Server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if skipRequestLog(r.URL.Path) {
			next.ServeHTTP(w, r)
			return
		}
		start := time.Now()
		request := readRequestSummary(r)
		rec := &statusRecorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)
		status := rec.status
		if status == 0 {
			status = http.StatusOK
		}
		// Successful reads are mostly status/log polling; keep the log focused
		// on operations and failures (errors are still recorded).
		if (r.Method == http.MethodGet || r.Method == http.MethodHead) && status < http.StatusBadRequest {
			return
		}
		query := ""
		if r.URL.RawQuery != "" {
			query = "?" + redactQuery(r.URL.RawQuery)
		}
		line := fmt.Sprintf(
			"api %s %s%s -> %d (%s, %dB)",
			r.Method, r.URL.Path, query, status,
			time.Since(start).Round(time.Millisecond), rec.bytes,
		)
		if request != "" {
			line += " | " + request
		}
		if status >= http.StatusBadRequest && rec.body.Len() > 0 {
			line += " | response=" + compactJSON(rec.body.Bytes())
		}
		fmt.Fprintln(LogSink(), line)
	})
}

func skipRequestLog(path string) bool {
	switch path {
	case "/health", "/v1/ws", "/", "/docs", "/openapi.yaml":
		return true
	}
	return strings.HasPrefix(path, "/ui/")
}

func redactQuery(raw string) string {
	values, err := url.ParseQuery(raw)
	if err != nil {
		return raw
	}
	for key := range values {
		switch strings.ToLower(key) {
		case "api_key", "apikey", "token", "access_token", "key", "password", "secret":
			values.Set(key, "***")
		}
	}
	return values.Encode()
}

// readRequestSummary reads a bounded, redacted copy of a JSON request body and
// restores the body for the handler.
func readRequestSummary(r *http.Request) string {
	if r.Body == nil || r.Method == http.MethodGet || r.Method == http.MethodHead {
		return ""
	}
	blob, err := io.ReadAll(io.LimitReader(r.Body, httpLogBodyLimit+1))
	if err != nil {
		return ""
	}
	r.Body = io.NopCloser(io.MultiReader(bytes.NewReader(blob), r.Body))
	if len(blob) > httpLogBodyLimit {
		blob = blob[:httpLogBodyLimit]
	}
	return compactJSON(blob)
}

// compactJSON redacts credentials and collapses whitespace; non-JSON bodies
// are only shown as their first line to avoid dumping binary/script content.
func compactJSON(blob []byte) string {
	var v any
	if err := json.Unmarshal(blob, &v); err != nil {
		text := strings.TrimSpace(string(blob))
		if i := strings.IndexByte(text, '\n'); i >= 0 {
			text = text[:i]
		}
		if len(text) > 200 {
			text = text[:200] + "…"
		}
		return text
	}
	redactSecrets(v)
	out, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	if len(out) > httpLogBodyLimit {
		return string(out[:httpLogBodyLimit]) + "…"
	}
	return string(out)
}

func redactSecrets(v any) {
	switch value := v.(type) {
	case map[string]any:
		for key, item := range value {
			switch strings.ToLower(key) {
			case "api_key", "apikey", "token", "authorization", "password", "secret":
				value[key] = "***"
			default:
				redactSecrets(item)
			}
		}
	case []any:
		for _, item := range value {
			redactSecrets(item)
		}
	}
}
