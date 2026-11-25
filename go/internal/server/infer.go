package server

import (
	"encoding/json"
	"net/http"
)

type modelRequest struct {
	Ref   string `json:"ref"`
	Async bool   `json:"async,omitempty"`
}

// loadModel is the legacy management "load" entry. It now means disk preload:
// resident start/stop is owned by the scheduler and starts on demand.
func (s *Server) loadModel(w http.ResponseWriter, r *http.Request) {
	var req modelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Ref == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	ready, jobID, err := s.ensurePreload(r.Context(), req.Ref)
	if err != nil {
		writeError(w, http.StatusNotImplemented, err)
		return
	}
	if ready {
		writeJSON(w, http.StatusOK, map[string]any{
			"ref": req.Ref, "preload": preloadReady, "state": preloadReady,
		})
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{
		"ref": req.Ref, "preload": preloadLoading, "job_id": jobID, "state": "running",
	})
}
