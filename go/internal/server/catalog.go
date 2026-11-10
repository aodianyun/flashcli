package server

import (
	"context"
	"net/http"
	"strconv"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
)

// CatalogSource is the public FlashHub catalog used by /v1/catalog.
type CatalogSource interface {
	ListRepositories(context.Context, string, int, string, int, int) ([]flashhub.Repository, int, error)
	GetRepository(context.Context, int) (flashhub.Repository, error)
	ListVersions(context.Context, int, int, int) ([]flashhub.Version, int, error)
	ListTags(context.Context) ([]flashhub.Tag, error)
}

func (s *Server) catalogRepos(w http.ResponseWriter, r *http.Request) {
	if s.Catalog == nil {
		http.Error(w, "catalog is not configured", http.StatusNotImplemented)
		return
	}
	q := r.URL.Query()
	page, _ := strconv.Atoi(q.Get("page"))
	pageSize, _ := strconv.Atoi(q.Get("page_size"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	tagID, _ := strconv.Atoi(q.Get("tag"))
	repos, total, err := s.Catalog.ListRepositories(r.Context(), q.Get("q"), tagID, q.Get("sort"), page, pageSize)
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"repos":     repos,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}

func (s *Server) catalogTags(w http.ResponseWriter, r *http.Request) {
	if s.Catalog == nil {
		http.Error(w, "catalog is not configured", http.StatusNotImplemented)
		return
	}
	tags, err := s.Catalog.ListTags(r.Context())
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"tags": tags})
}

func (s *Server) catalogRepo(w http.ResponseWriter, r *http.Request) {
	if s.Catalog == nil {
		http.Error(w, "catalog is not configured", http.StatusNotImplemented)
		return
	}
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil || id <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid repository id"})
		return
	}
	repo, err := s.Catalog.GetRepository(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	versions, total, err := s.Catalog.ListVersions(r.Context(), id, 1, 100)
	if err != nil {
		writeError(w, http.StatusBadGateway, err)
		return
	}
	if len(versions) > 0 {
		repo.LatestVersion = versions[0].Version
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"repo":     repo,
		"versions": versions,
		"total":    total,
	})
}
