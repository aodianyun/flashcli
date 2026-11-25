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
// models whose assets are locally available, using the OpenAI list shape.
// FlashHub catalog browsing stays on the management API (/api/v1/catalog).
//
// Until preload state lands (M1), "locally available" means resident.
func (s *Server) gatewayModels(w http.ResponseWriter, _ *http.Request) {
	now := time.Now().Unix()
	data := make([]OpenAIModel, 0)
	if s.Manager != nil {
		for _, inst := range s.Manager.List() {
			created := inst.LoadedAt.Unix()
			if created == 0 {
				created = now
			}
			data = append(data, OpenAIModel{
				ID:           inst.Ref,
				Object:       "model",
				Created:      created,
				OwnedBy:      "flashcli",
				Capabilities: inst.Capabilities,
			})
		}
	}
	sort.Slice(data, func(i, j int) bool { return data[i].ID < data[j].ID })
	writeJSON(w, http.StatusOK, map[string]any{"object": "list", "data": data})
}
