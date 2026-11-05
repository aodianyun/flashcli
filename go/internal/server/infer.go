package server

import (
	"encoding/json"
	"errors"
	"net/http"
)

type modelRequest struct {
	Ref string `json:"ref"`
}

func (s *Server) loadModel(w http.ResponseWriter, r *http.Request) {
	var req modelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Ref == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	if s.Manager == nil {
		writeError(w, http.StatusNotImplemented, errors.New("model manager is not configured"))
		return
	}
	info, err := s.Manager.Load(r.Context(), req.Ref)
	if err != nil {
		status := http.StatusBadRequest
		if errors.Is(err, ErrResourceExhausted) {
			status = http.StatusConflict
		}
		writeError(w, status, err)
		return
	}
	writeJSON(w, http.StatusOK, info)
}

func (s *Server) unloadModel(w http.ResponseWriter, r *http.Request) {
	var req modelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Ref == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "ref is required"})
		return
	}
	if s.Manager == nil {
		writeError(w, http.StatusNotImplemented, errors.New("model manager is not configured"))
		return
	}
	if err := s.Manager.Unload(r.Context(), req.Ref); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ref": req.Ref, "state": "unloaded"})
}
