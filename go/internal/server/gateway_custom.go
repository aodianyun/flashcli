package server

import (
	"bytes"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
)

// gatewayCustom handles every /v1/* path that is not an explicit host route.
// The bundle owns the path contract; the gateway only selects the model,
// manages its lifecycle, and forwards the request unchanged. This keeps the
// host model-agnostic: OCR, ASR, audio-separation, and video-erase paths never
// need a per-route allowlist in go/.
func (s *Server) gatewayCustom(w http.ResponseWriter, r *http.Request) {
	if s.gatewayReserved(w, r) {
		return
	}
	if strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
		writeGatewayError(w, http.StatusNotImplemented, "custom_websocket_unsupported", "invalid_request_error",
			"custom WebSocket routes are not supported; use /v1/realtime", "", "", 0)
		return
	}
	refStr, body, contentLength, fail := s.customGatewayRequest(w, r)
	if fail != nil {
		fail.write(w)
		return
	}
	s.serveModelRequest(w, r, "", r.URL.EscapedPath(), stripGatewayModelQuery(r.URL.RawQuery),
		refStr, body, contentLength)
}

// gatewayReserved reports whether the path belongs to a host-owned route. It
// exists because the /v1/ catch-all also matches a standard path with the
// wrong method (a method-less pattern matches every method), which would
// otherwise turn a 405 into a custom passthrough.
func (s *Server) gatewayReserved(w http.ResponseWriter, r *http.Request) bool {
	methods, reserved := gatewayReservedMethods(r.URL.Path)
	if !reserved {
		return false
	}
	if methods == nil {
		writeGatewayError(w, http.StatusNotFound, "not_found", "invalid_request_error", "route not found", "", "", 0)
		return true
	}
	if !gatewayMethodAllowed(methods, r.Method) {
		w.Header().Set("Allow", strings.Join(methods, ", "))
		writeGatewayError(w, http.StatusMethodNotAllowed, "method_not_allowed", "invalid_request_error", "method not allowed", "", "", 0)
		return true
	}
	// A known method on a reserved path should have matched its explicit
	// handler; reaching the catch-all means the path is malformed.
	writeGatewayError(w, http.StatusNotFound, "not_found", "invalid_request_error", "route not found", "", "", 0)
	return true
}

func gatewayReservedMethods(path string) ([]string, bool) {
	// A standard path with one trailing slash is a malformed host route, not a
	// custom path. Keep it reserved so a typo cannot auto-pull/start a model.
	if path != "/" && strings.HasSuffix(path, "/") {
		if methods, ok := gatewayReservedMethods(strings.TrimSuffix(path, "/")); ok {
			return methods, true
		}
	}
	if path == "/v1/videos" {
		return []string{http.MethodPost, http.MethodGet, http.MethodHead}, true
	}
	if _, ok := gatewayJSONRoutes[path]; ok {
		return []string{http.MethodPost}, true
	}
	if _, ok := gatewayMultipartRoutes[path]; ok {
		return []string{http.MethodPost}, true
	}
	switch path {
	case "/v1/models":
		return []string{http.MethodGet, http.MethodHead}, true
	case "/v1/realtime":
		return []string{http.MethodGet, http.MethodHead}, true
	}
	if strings.HasPrefix(path, "/v1/models/") {
		return []string{http.MethodGet, http.MethodHead}, true
	}
	if rest, ok := strings.CutPrefix(path, "/v1/videos/"); ok {
		segments := strings.Split(rest, "/")
		switch {
		case len(segments) == 1 && segments[0] != "":
			return []string{http.MethodGet, http.MethodHead, http.MethodDelete}, true
		case len(segments) == 2 && segments[0] != "" && segments[1] == "content":
			return []string{http.MethodGet, http.MethodHead}, true
		default:
			return nil, true
		}
	}
	if rest, ok := strings.CutPrefix(path, "/v1/responses/"); ok {
		segments := strings.Split(rest, "/")
		switch {
		case len(segments) == 1 && segments[0] != "":
			return []string{http.MethodGet, http.MethodHead, http.MethodDelete}, true
		case len(segments) == 2 && segments[0] != "" && segments[1] == "cancel":
			return []string{http.MethodPost}, true
		default:
			return nil, true
		}
	}
	return nil, false
}

func gatewayMethodAllowed(methods []string, method string) bool {
	for _, m := range methods {
		if m == method {
			return true
		}
	}
	return false
}

// customGatewayRequest extracts the selected model and the body to forward.
// JSON and multipart bodies carry `model`; other methods/content types select
// the model with `?model=` and stream their body untouched.
func (s *Server) customGatewayRequest(w http.ResponseWriter, r *http.Request) (string, io.Reader, int64, *gatewayFailure) {
	queryRef := r.URL.Query().Get("model")
	mediaType, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
	switch {
	case mediaType == "application/json" || strings.HasSuffix(mediaType, "+json"):
		body, err := io.ReadAll(io.LimitReader(r.Body, gatewayMaxBody+1))
		if err != nil {
			return "", nil, 0, &gatewayFailure{Status: http.StatusBadRequest, Code: "invalid_request_error", Type: "invalid_request_error",
				Message: "cannot read request body"}
		}
		if len(body) > gatewayMaxBody {
			return "", nil, 0, &gatewayFailure{Status: http.StatusRequestEntityTooLarge, Code: "request_too_large", Type: "invalid_request_error",
				Message: "request body is too large"}
		}
		if len(bytes.TrimSpace(body)) == 0 {
			// An empty body is valid for a POST that selects its model with
			// ?model=; forward the exact empty body.
			refStr, fail := resolveGatewayModel("", queryRef)
			if fail != nil {
				return "", nil, 0, fail
			}
			return refStr, bytes.NewReader(body), int64(len(body)), nil
		}
		var parsed struct {
			Model string `json:"model"`
		}
		if !json.Valid(body) {
			return "", nil, 0, &gatewayFailure{Status: http.StatusBadRequest, Code: "invalid_json", Type: "invalid_request_error",
				Message: "request body must be valid JSON"}
		}
		// Custom bodies are bundle-owned and may be arrays or scalars. Only an
		// object `model` string acts as the selector; otherwise the query
		// selector is used.
		var object map[string]json.RawMessage
		_ = json.Unmarshal(body, &object)
		if raw, ok := object["model"]; ok {
			if err := json.Unmarshal(raw, &parsed.Model); err != nil {
				return "", nil, 0, &gatewayFailure{Status: http.StatusBadRequest, Code: "invalid_model", Type: "invalid_request_error",
					Message: "model must be a string"}
			}
		}
		refStr, fail := resolveGatewayModel(parsed.Model, queryRef)
		if fail != nil {
			return "", nil, 0, fail
		}
		return refStr, bytes.NewReader(body), int64(len(body)), nil
	case mediaType == "multipart/form-data":
		bodyRef, body, fail := s.readMultipartModel(w, r)
		if fail != nil {
			return "", nil, 0, fail
		}
		refStr, fail := resolveGatewayModel(bodyRef, queryRef)
		if fail != nil {
			return "", nil, 0, fail
		}
		return refStr, bytes.NewReader(body), int64(len(body)), nil
	default:
		refStr, fail := resolveGatewayModel("", queryRef)
		if fail != nil {
			return "", nil, 0, fail
		}
		return refStr, gatewayStreamBody(r), gatewayStreamLength(r), nil
	}
}

func gatewayStreamBody(r *http.Request) io.Reader {
	if r.Body == nil || r.Body == http.NoBody || r.ContentLength == 0 {
		return nil
	}
	return r.Body
}

func gatewayStreamLength(r *http.Request) int64 {
	if r.Body == nil || r.Body == http.NoBody || r.ContentLength == 0 {
		return 0
	}
	return r.ContentLength
}

// stripGatewayModelQuery removes the gateway selector and leaves every other
// query parameter byte-for-byte intact.
func stripGatewayModelQuery(rawQuery string) string {
	if rawQuery == "" {
		return ""
	}
	parts := strings.Split(rawQuery, "&")
	kept := parts[:0]
	for _, part := range parts {
		if part == "" {
			continue
		}
		key := part
		if i := strings.IndexByte(part, '='); i >= 0 {
			key = part[:i]
		}
		if unescaped, err := url.QueryUnescape(key); err == nil {
			key = unescaped
		}
		if key == "model" {
			continue
		}
		kept = append(kept, part)
	}
	return strings.Join(kept, "&")
}

// serveQueryModel implements the standard routes that carry the model in the
// query string because they have no JSON body (video list/get/delete/content).
func (s *Server) serveQueryModel(w http.ResponseWriter, r *http.Request, capability, upstreamPath string) {
	refStr, fail := resolveGatewayModel("", r.URL.Query().Get("model"))
	if fail != nil {
		fail.write(w)
		return
	}
	s.serveModelRequest(w, r, capability, upstreamPath, stripGatewayModelQuery(r.URL.RawQuery),
		refStr, nil, 0)
}

func (s *Server) gatewayVideoList(w http.ResponseWriter, r *http.Request) {
	s.serveQueryModel(w, r, "openai.videos", "/v1/videos")
}

func (s *Server) gatewayVideo(w http.ResponseWriter, r *http.Request) {
	s.serveQueryModel(w, r, "openai.videos", r.URL.EscapedPath())
}

func (s *Server) gatewayVideoContent(w http.ResponseWriter, r *http.Request) {
	s.serveQueryModel(w, r, "openai.videos", r.URL.EscapedPath())
}

func (s *Server) gatewayResponse(w http.ResponseWriter, r *http.Request) {
	s.serveQueryModel(w, r, "openai.responses", r.URL.EscapedPath())
}

func (s *Server) gatewayResponseCancel(w http.ResponseWriter, r *http.Request) {
	s.serveQueryModel(w, r, "openai.responses", r.URL.EscapedPath())
}
