package server

import (
	"encoding/json"
	"net/http"
	"os"

	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/version"
)

// mirrorState is the flat mirror block used by the settings payload and the
// management WebSocket ("mirror" events).
func mirrorState() map[string]any {
	mirror.Apply()
	return map[string]any{
		"enabled":       mirror.Enabled(),
		"pip_index_url": os.Getenv("PIP_INDEX_URL"),
		"hf_endpoint":   os.Getenv("HF_ENDPOINT"),
		"git_proxy":     os.Getenv("FLASHCLI_GIT_PROXY"),
		"install_repo":  os.Getenv("FLASHCLI_INSTALL_REPO"),
	}
}

// settingsPayload is the read model for GET /api/v1/settings. Only fields
// listed in `writable` may be changed through PATCH; the rest are effective
// values from the daemon config and process environment.
func (s *Server) settingsPayload() map[string]any {
	maxLoaded := 0
	if s.Manager != nil {
		_, maxLoaded = s.Manager.Slots()
	}
	return map[string]any{
		"mirror": mirrorState(),
		"scheduler": map[string]any{
			"vram_headroom_mib":           s.vramHeadroomMiB(),
			"max_loaded":                  maxLoaded,
			"idle_stop_seconds":           s.IdleStopSeconds,
			"resident_start_wait_seconds": s.ResidentStartWaitSeconds,
			"queue_timeout_seconds":       s.QueueTimeoutSeconds,
			"queue_max":                   s.QueueMax,
			"auto_pull":                   s.AutoPull,
			"cpu_fallback":                s.CPUFallback,
		},
		"server": map[string]any{
			"addr":         s.Addr,
			"auth_enabled": s.Token != "",
			"version":      version.Version,
		},
		"paths": map[string]any{
			"home":    paths.Home(),
			"bundles": paths.Bundles(),
			"models":  paths.Models(),
		},
		"writable": []string{"mirror.enabled"},
	}
}

func (s *Server) getSettings(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, s.settingsPayload())
}

// patchSettings serves PATCH /api/v1/settings. The body is a partial typed
// object; unknown or read-only sections are rejected instead of silently
// ignored. Currently mirror.enabled is the only hot-writable setting.
func (s *Server) patchSettings(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Mirror *struct {
			Enabled *bool `json:"enabled"`
		} `json:"mirror"`
		Scheduler json.RawMessage `json:"scheduler"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, err)
		return
	}
	if len(req.Scheduler) > 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "scheduler settings are read-only; edit the daemon config and restart",
		})
		return
	}
	if req.Mirror == nil || req.Mirror.Enabled == nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "no writable setting: send {\"mirror\":{\"enabled\":true|false}}",
		})
		return
	}
	if err := mirror.SetEnabled(*req.Mirror.Enabled); err != nil {
		writeError(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, s.settingsPayload())
}
