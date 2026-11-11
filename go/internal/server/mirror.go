package server

import (
	"encoding/json"
	"net/http"
	"os"

	"github.com/aodianyun/flashcli/go/internal/mirror"
)

func mirrorPayload() map[string]any {
	mirror.Apply()
	return map[string]any{
		"enabled":       mirror.Enabled(),
		"pip_index_url": os.Getenv("PIP_INDEX_URL"),
		"hf_endpoint":   os.Getenv("HF_ENDPOINT"),
		"git_proxy":     os.Getenv("FLASHCLI_GIT_PROXY"),
		"install_repo":  os.Getenv("FLASHCLI_INSTALL_REPO"),
	}
}

func (s *Server) mirrorStatus(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, mirrorPayload())
}

func (s *Server) setMirror(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Enabled bool `json:"enabled"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "enabled is required"})
		return
	}
	if err := mirror.SetEnabled(req.Enabled); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, mirrorPayload())
}
