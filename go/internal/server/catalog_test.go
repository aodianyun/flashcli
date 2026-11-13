package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
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

type emptyCatalog struct{}

func (emptyCatalog) ListRepositories(context.Context, string, int, string, int, int) ([]flashhub.Repository, int, error) {
	return nil, 0, nil
}

func (emptyCatalog) GetRepository(context.Context, int) (flashhub.Repository, error) {
	return flashhub.Repository{}, nil
}

func (emptyCatalog) ListVersions(context.Context, int, int, int) ([]flashhub.Version, int, error) {
	return nil, 0, nil
}

func (emptyCatalog) ListTags(context.Context) ([]flashhub.Tag, error) {
	return nil, nil
}

func TestCatalogEmptyResultIsAnArray(t *testing.T) {
	s := &Server{Catalog: emptyCatalog{}}
	h := s.Handler()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/v1/catalog?q=spark_x26_1p7b&tag=1", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	var payload struct {
		Repos json.RawMessage `json:"repos"`
		Total int             `json:"total"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if string(payload.Repos) != "[]" {
		t.Fatalf("repos = %s, want [] (no matches is not an error)", payload.Repos)
	}
	if payload.Total != 0 {
		t.Fatalf("total = %d, want 0", payload.Total)
	}

	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/v1/catalog/tags", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("tags status = %d", rec.Code)
	}
	if body := rec.Body.String(); !strings.Contains(body, `"tags":[]`) {
		t.Fatalf("tags = %s, want []", body)
	}
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
