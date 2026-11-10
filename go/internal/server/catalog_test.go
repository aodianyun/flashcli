package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
)

type fakeCatalog struct{}

func (fakeCatalog) ListRepositories(context.Context, string, int, string, int, int) ([]flashhub.Repository, int, error) {
	return []flashhub.Repository{{
		ID: 5, Name: "pi05_libero", Namespace: "flashcli-bundle", ModelName: "lerobot/pi05",
		VersionCount: 4, Tags: []flashhub.Tag{{ID: 1, Name: "VLA"}},
	}}, 1, nil
}

func (fakeCatalog) GetRepository(context.Context, int) (flashhub.Repository, error) {
	return flashhub.Repository{ID: 5, Name: "pi05_libero", Namespace: "flashcli-bundle"}, nil
}

func (fakeCatalog) ListVersions(context.Context, int, int, int) ([]flashhub.Version, int, error) {
	return []flashhub.Version{{ID: 26, Version: "1.0.4", Size: 471834099}}, 1, nil
}

func (fakeCatalog) ListTags(context.Context) ([]flashhub.Tag, error) {
	return []flashhub.Tag{{ID: 1, Name: "VLA", NameCN: "VLA"}}, nil
}

func TestCatalogEndpoints(t *testing.T) {
	s := &Server{Catalog: fakeCatalog{}}
	h := s.Handler()
	for _, path := range []string{"/v1/catalog?q=pi05", "/v1/catalog/tags", "/v1/catalog/5"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		if rec.Code != http.StatusOK {
			t.Fatalf("%s: status = %d body=%s", path, rec.Code, rec.Body.String())
		}
		var payload map[string]any
		if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		if len(payload) == 0 {
			t.Fatalf("%s: empty payload", path)
		}
	}
}
