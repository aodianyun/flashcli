package server

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
)

type modelRequest struct {
	Ref   string `json:"ref"`
	Async bool   `json:"async,omitempty"`
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
	if req.Async {
		if s.Jobs == nil {
			writeError(w, http.StatusNotImplemented, errors.New("job manager is not configured"))
			return
		}
		refStr := req.Ref
		job := s.Jobs.Start(context.Background(), "load", refStr, func(ctx context.Context, emit func(string, string)) error {
			emit("loading", "loading "+refStr)
			info, err := s.Manager.Load(ctx, refStr)
			if err != nil {
				return err
			}
			emit("ready", info.Endpoint)
			return nil
		})
		writeJSON(w, http.StatusAccepted, map[string]any{"job_id": job.ID, "state": job.State})
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
