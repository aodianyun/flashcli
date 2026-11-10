package flashhub

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// DefaultWebAPIBase is the public FlashHub web API (catalog, tags, versions).
const DefaultWebAPIBase = "https://flashhub-api.aodianyun.com/api/v1"

// WebAPIBase resolves FLASHCLI_FLASHHUB_WEB_API, deriving it from
// FLASHCLI_FLASHHUB_API (.../repos) when only the repo API is overridden.
func WebAPIBase() string {
	if v := strings.TrimRight(strings.TrimSpace(os.Getenv("FLASHCLI_FLASHHUB_WEB_API")), "/"); v != "" {
		return v
	}
	base := strings.TrimRight(APIBase(), "/")
	if strings.HasSuffix(base, "/repos") {
		return strings.TrimSuffix(base, "/repos")
	}
	return DefaultWebAPIBase
}

// Tag is one public repository category.
type Tag struct {
	ID     int    `json:"id"`
	Name   string `json:"name"`
	NameCN string `json:"name_cn"`
}

// Version is one repository version.
type Version struct {
	ID            int    `json:"id"`
	Version       string `json:"version"`
	Size          int64  `json:"size"`
	FileCount     int    `json:"file_count"`
	ReleaseStatus string `json:"release_status,omitempty"`
	Status        string `json:"status,omitempty"`
	CreatedAt     string `json:"created_at,omitempty"`
}

// Repository is one public FlashHub repository.
type Repository struct {
	ID           int    `json:"id"`
	Name         string `json:"name"`
	Namespace    string `json:"namespace"`
	Organization struct {
		Name        string `json:"name"`
		DisplayName string `json:"display_name"`
	} `json:"organization"`
	ModelName     string    `json:"model_name"`
	VersionCount  int       `json:"version_count"`
	Downloads     int       `json:"downloads"`
	UpdatedAt     string    `json:"updated_at,omitempty"`
	LatestVersion string    `json:"latest_version,omitempty"`
	Tags          []Tag     `json:"tags"`
	Versions      []Version `json:"versions,omitempty"`
}

type catalogEnvelope struct {
	Code    *int            `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
}

type repoList struct {
	List     []Repository `json:"list"`
	Total    int          `json:"total"`
	Page     int          `json:"page"`
	PageSize int          `json:"page_size"`
}

type versionList struct {
	List     []Version `json:"list"`
	Total    int       `json:"total"`
	Page     int       `json:"page"`
	PageSize int       `json:"page_size"`
}

// ListTags returns the public repository categories.
func (c *Client) ListTags(ctx context.Context) ([]Tag, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	var tags []Tag
	if err := c.catalogGet(ctx, WebAPIBase()+"/tags", &tags); err != nil {
		return nil, err
	}
	return tags, nil
}

// ListRepositories searches the public catalog.
func (c *Client) ListRepositories(ctx context.Context, search string, tagID int, sort string, page, pageSize int) ([]Repository, int, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	u, err := url.Parse(WebAPIBase() + "/repositories")
	if err != nil {
		return nil, 0, err
	}
	q := u.Query()
	if search = strings.TrimSpace(search); search != "" {
		q.Set("search", search)
	}
	if tagID > 0 {
		q.Set("tag_id", strconv.Itoa(tagID))
	}
	if sort != "" {
		q.Set("sort", sort)
	}
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 20
	}
	q.Set("page", strconv.Itoa(page))
	q.Set("page_size", strconv.Itoa(pageSize))
	u.RawQuery = q.Encode()

	var out repoList
	if err := c.catalogGet(ctx, u.String(), &out); err != nil {
		return nil, 0, err
	}
	for i := range out.List {
		normalizeRepo(&out.List[i])
	}
	return out.List, out.Total, nil
}

// GetRepository returns one repository with its version list.
func (c *Client) GetRepository(ctx context.Context, id int) (Repository, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	var repo Repository
	if err := c.catalogGet(ctx, fmt.Sprintf("%s/repositories/%d", WebAPIBase(), id), &repo); err != nil {
		return Repository{}, err
	}
	normalizeRepo(&repo)
	return repo, nil
}

// ListVersions returns the versions of one repository.
func (c *Client) ListVersions(ctx context.Context, id, page, pageSize int) ([]Version, int, error) {
	ctx, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 20
	}
	u := fmt.Sprintf("%s/repositories/%d/versions?page=%d&page_size=%d", WebAPIBase(), id, page, pageSize)
	var out versionList
	if err := c.catalogGet(ctx, u, &out); err != nil {
		return nil, 0, err
	}
	return out.List, out.Total, nil
}

func (c *Client) catalogGet(ctx context.Context, rawURL string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	client := c.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("FlashHub %s: HTTP %d", rawURL, resp.StatusCode)
	}
	var env catalogEnvelope
	if err := json.NewDecoder(resp.Body).Decode(&env); err != nil {
		return fmt.Errorf("FlashHub response is not JSON: %w", err)
	}
	if env.Code != nil && *env.Code != 0 {
		return fmt.Errorf("FlashHub API error (code=%d): %s", *env.Code, env.Message)
	}
	if len(env.Data) == 0 {
		return nil
	}
	return json.Unmarshal(env.Data, out)
}

func normalizeRepo(r *Repository) {
	r.Namespace = strings.TrimSpace(r.Namespace)
	if r.Namespace == "" {
		r.Namespace = strings.TrimSpace(r.Organization.Name)
	}
	if r.Namespace == "" {
		r.Namespace = "flashcli-bundle"
	}
	if len(r.Versions) > 0 {
		r.LatestVersion = r.Versions[0].Version
	}
}
