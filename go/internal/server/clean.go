package server

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/host"
)

type cleanRequest struct {
	Refs []string `json:"refs"`
}

type cleanResult struct {
	Ref           string `json:"ref"`
	Removed       bool   `json:"removed"`
	FreedBytes    int64  `json:"freed_bytes"`
	Skipped       string `json:"skipped,omitempty"`
	SharedBundle  bool   `json:"shared_bundle,omitempty"`
	SharedWeights bool   `json:"shared_weights,omitempty"`
}

type storageCleanRequest struct {
	Targets []string `json:"targets"`
}

// cleanModels removes local bundle/weights/runtime caches for the requested
// refs. Loaded or in-flight models are skipped; shared weights/runtime are kept
// while another cached ref still references them.
func (s *Server) cleanModels(w http.ResponseWriter, r *http.Request) {
	var req cleanRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.Refs) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "refs is required"})
		return
	}
	if len(req.Refs) > 100 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "too many refs (max 100)"})
		return
	}
	loaded := map[string]bool{}
	for _, inst := range s.loaded() {
		loaded[inst.Ref] = true
	}
	results := make([]cleanResult, 0, len(req.Refs))
	var total int64
	for _, raw := range req.Refs {
		ref := strings.TrimSpace(raw)
		if ref == "" {
			continue
		}
		if loaded[ref] {
			results = append(results, cleanResult{Ref: ref, Skipped: "loaded"})
			continue
		}
		if s.Manager != nil && s.Manager.Busy(ref) {
			results = append(results, cleanResult{Ref: ref, Skipped: "busy"})
			continue
		}
		res, err := host.RemoveCachedRef(ref)
		if err != nil {
			results = append(results, cleanResult{Ref: ref, Skipped: err.Error()})
			continue
		}
		total += res.FreedBytes
		results = append(results, cleanResult{
			Ref:           ref,
			Removed:       res.Removed,
			FreedBytes:    res.FreedBytes,
			SharedBundle:  res.SharedBundle,
			SharedWeights: res.SharedWeights,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": results, "freed_bytes": total})
}

// cleanStorage removes the shared cache group (downloads/Python/uv). Model
// runtimes are removed per ref by cleanModels, matching `flashcli bundle clean`.
func (s *Server) cleanStorage(w http.ResponseWriter, r *http.Request) {
	var req storageCleanRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.Targets) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "targets is required"})
		return
	}
	for _, target := range req.Targets {
		if target == "runtimes" || target == "all" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "model runtimes are removed per ref via /v1/models/clean"})
			return
		}
	}
	freed, err := host.CleanSharedCaches(req.Targets)
	if err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"freed_bytes": freed, "targets": req.Targets})
}
