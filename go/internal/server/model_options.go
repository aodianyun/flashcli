package server

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/serveopts"
)

type modelOptionsRequest struct {
	Ref     string            `json:"ref"`
	Host    string            `json:"host"`
	Port    int               `json:"port"`
	Options map[string]string `json:"options"`
}

// getModelOptions returns the manifest serve options plus the saved values.
func (s *Server) getModelOptions(w http.ResponseWriter, r *http.Request) {
	refStr := strings.TrimSpace(r.URL.Query().Get("ref"))
	if refStr == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	bundle, err := inspectBundle(refStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	saved := ModelServeSettings{}
	if s.ServeSettings != nil {
		saved = s.ServeSettings.Get(refStr)
	}
	defaultHost := strings.TrimSpace(s.ServeHost)
	if defaultHost == "" {
		defaultHost = "127.0.0.1"
	}
	host := saved.Host
	if host == "" {
		host = defaultHost
	}
	values := saved.Options
	if values == nil {
		values = map[string]string{}
	}
	options := make([]map[string]any, 0, len(bundle.ServeOptions))
	for _, spec := range bundle.ServeOptions {
		if spec.HostLevel {
			continue
		}
		item := map[string]any{
			"name":  spec.Name,
			"flag":  spec.Flag,
			"type":  spec.Type,
			"help":  spec.Help,
			"phase": spec.Phase,
			"value": values[spec.Name],
		}
		if spec.Default != nil {
			item["default"] = spec.Default
		}
		options = append(options, item)
	}
	restart := s.Manager != nil && s.Manager.Busy(refStr)
	writeJSON(w, http.StatusOK, map[string]any{
		"ref":              refStr,
		"host":             host,
		"default_host":     defaultHost,
		"public_host":      s.PublicHost,
		"port":             saved.Port,
		"options":          options,
		"restart_required": restart,
	})
}

// putModelOptions saves host/port/serve options for one model. Empty option
// values mean "use the bundle default" and are not passed to flashcli serve.
func (s *Server) putModelOptions(w http.ResponseWriter, r *http.Request) {
	var req modelOptionsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || strings.TrimSpace(req.Ref) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	refStr := strings.TrimSpace(req.Ref)
	bundle, err := inspectBundle(refStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	host := strings.TrimSpace(req.Host)
	if host != "" && !validServeHost(host) {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": fmt.Sprintf("invalid host %q", host)})
		return
	}
	if req.Port < 0 || req.Port > 65535 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "port must be between 1 and 65535 (0 = auto)"})
		return
	}
	values, err := serveopts.Validate(bundle.ServeOptions, req.Options)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": err.Error()})
		return
	}
	if s.ServeSettings == nil {
		s.ServeSettings = newServeSettingsStore("")
	}
	if err := s.ServeSettings.Set(refStr, ModelServeSettings{Host: host, Port: req.Port, Options: values}); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	if s.Manager != nil && s.Manager.opts.ServeSettings == nil {
		s.Manager.opts.ServeSettings = s.ServeSettings
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"ref":              refStr,
		"host":             host,
		"port":             req.Port,
		"options":          values,
		"restart_required": s.Manager != nil && s.Manager.Busy(refStr),
	})
}

func (s *Server) deleteModelOptions(w http.ResponseWriter, r *http.Request) {
	refStr := strings.TrimSpace(r.URL.Query().Get("ref"))
	if refStr == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	if s.ServeSettings != nil {
		if err := s.ServeSettings.Delete(refStr); err != nil {
			writeError(w, http.StatusInternalServerError, err)
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"ref": refStr, "state": "defaults"})
}

func validServeHost(host string) bool {
	if host == "localhost" {
		return true
	}
	if net.ParseIP(host) != nil {
		return true
	}
	for _, r := range host {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || r == '.' || r == '-' || r == '_' {
			continue
		}
		return false
	}
	return host != "" && !strings.HasPrefix(host, "-") && !strings.HasSuffix(host, "-")
}
