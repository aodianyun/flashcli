package flashhub

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
)

// AppBundleRef is one bundle entry in an application listing.
type AppBundleRef struct {
	Bundle    string `json:"bundle"`
	IsDefault bool   `json:"is_default"`
}

// AppOrganization is the publishing organization of an application.
type AppOrganization struct {
	Name        string `json:"name"`
	DisplayName string `json:"display_name"`
	Logo        string `json:"logo"`
}

// AppSummary is one item from GET /api/v1/apps.
type AppSummary struct {
	ID              int               `json:"id"`
	Name            string            `json:"name"`
	DisplayName     string            `json:"display_name"`
	Domain          string            `json:"domain"`
	Version         string            `json:"version"`
	Description     string            `json:"description"`
	DescriptionEN   string            `json:"description_en"`
	CoverURL        string            `json:"cover_url"`
	Status          string            `json:"status"`
	Downloads       int               `json:"downloads"`
	Organization    AppOrganization   `json:"organization"`
	SupportedOS     []string          `json:"supported_os"`
	SupportedArch   []string          `json:"supported_arch"`
	InstallCommands map[string]string `json:"install_commands"`
	ModelBundles    []AppBundleRef    `json:"model_bundles"`
}

type appListEnvelope struct {
	Code    *int   `json:"code"`
	Message string `json:"message"`
	Data    struct {
		List     []AppSummary `json:"list"`
		Total    int          `json:"total"`
		Page     int          `json:"page"`
		PageSize int          `json:"page_size"`
	} `json:"data"`
}

// ListApps returns one page of applications (search/domain are optional).
func (c *Client) ListApps(ctx context.Context, search, domain string, page, pageSize int) ([]AppSummary, int, error) {
	if page <= 0 {
		page = 1
	}
	if pageSize <= 0 {
		pageSize = 20
	}
	q := url.Values{}
	q.Set("page", strconv.Itoa(page))
	q.Set("page_size", strconv.Itoa(pageSize))
	if search = trimSpace(search); search != "" {
		q.Set("search", search)
	}
	if domain = trimSpace(domain); domain != "" {
		q.Set("domain", domain)
	}
	blob, err := c.get(ctx, AppsBase()+"?"+q.Encode())
	if err != nil {
		return nil, 0, err
	}
	var env appListEnvelope
	if err := json.Unmarshal(blob, &env); err != nil {
		return nil, 0, fmt.Errorf("FlashHub application list is not JSON: %w", err)
	}
	if env.Code != nil && *env.Code != 0 {
		return nil, 0, fmt.Errorf("FlashHub application error (code=%d): %s", *env.Code, env.Message)
	}
	return env.Data.List, env.Data.Total, nil
}

func trimSpace(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\t' || s[0] == '\n' || s[0] == '\r') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\t' || s[len(s)-1] == '\n' || s[len(s)-1] == '\r') {
		s = s[:len(s)-1]
	}
	return s
}
