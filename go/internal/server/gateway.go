package server

import (
	"net/http"
	"sort"
	"time"
)

// OpenAIModel is one entry in an OpenAI `GET /v1/models` response.
type OpenAIModel struct {
	ID           string   `json:"id"`
	Object       string   `json:"object"`
	Created      int64    `json:"created"`
	OwnedBy      string   `json:"owned_by"`
	Capabilities []string `json:"capabilities,omitempty"`
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
