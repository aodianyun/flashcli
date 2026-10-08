// Package flashhub is a Go client for the FlashHub bundle repo API.
//
// Mirrors flashcli_bundle/flashhub.py: repo URL = {base}/{ns}/{name}:{version},
// index = {code:0, data:{files:[{download_url,file_name,file_size,md5_hash}]}}.
package flashhub

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

// DefaultAPIBase is the default FlashHub repos API.
const DefaultAPIBase = "https://flashhub-api.aodianyun.com/api/v1/repos"

// ManifestPath is the bundle manifest filename within a repo.
const ManifestPath = "flashcli-bundle.json"

var cdnPathRe = regexp.MustCompile(`/repo/\d+/versions/\d+/(.*)$`)

// APIBase resolves FLASHCLI_FLASHHUB_API (default DefaultAPIBase).
func APIBase() string {
	if v := strings.TrimRight(strings.TrimSpace(os.Getenv("FLASHCLI_FLASHHUB_API")), "/"); v != "" {
		return v
	}
	return DefaultAPIBase
}

// RepoURL builds the repo API URL.
func RepoURL(base, namespace, name, version string) (string, error) {
	ns := strings.Trim(strings.TrimSpace(namespace), "/")
	n := strings.Trim(strings.TrimSpace(name), "/")
	v := strings.TrimSpace(version)
	if ns == "" || n == "" || v == "" {
		return "", fmt.Errorf("invalid FlashHub repo parts: namespace=%q name=%q version=%q", namespace, name, version)
	}
	if strings.TrimSpace(base) == "" {
		base = APIBase()
	}
	return strings.TrimRight(base, "/") + "/" + ns + "/" + n + ":" + v, nil
}

// File is one downloadable repo file.
type File struct {
	Path string
	URL  string
	Size int64
	MD5  string
}

// Index is a parsed repo index.
type Index struct {
	RepoURL string
	Files   []File
}

// Find locates a file by bundle-relative path (exact, then suffix/basename).
func (ix *Index) Find(relPath string) *File {
	want := strings.Trim(strings.TrimSpace(relPath), "/")
	for i := range ix.Files {
		if ix.Files[i].Path == want {
			return &ix.Files[i]
		}
	}
	wantBase := want
	if idx := strings.LastIndex(want, "/"); idx >= 0 {
		wantBase = want[idx+1:]
	}
	for i := range ix.Files {
		if strings.HasSuffix(ix.Files[i].Path, "/"+want) || filepath.Base(ix.Files[i].Path) == wantBase {
			return &ix.Files[i]
		}
	}
	return nil
}

// Client fetches repo indices and files.
type Client struct {
	HTTP      *http.Client
	CacheDir  string
	UserAgent string
}

// NewClient returns a client with defaults.
func NewClient() *Client {
	return &Client{HTTP: http.DefaultClient, CacheDir: filepath.Join(paths.Cache(), "repo-index")}
}

type indexResponse struct {
	Code    *int   `json:"code"`
	Message string `json:"message"`
	Data    struct {
		Files []struct {
			DownloadURL string `json:"download_url"`
			FileName    string `json:"file_name"`
			FileSize    *int64 `json:"file_size"`
			MD5Hash     string `json:"md5_hash"`
		} `json:"files"`
	} `json:"data"`
}

// FetchIndex downloads and parses the repo index (optionally cached).
func (c *Client) FetchIndex(ctx context.Context, repoURL string, useCache bool) (*Index, error) {
	repoURL = strings.TrimRight(strings.TrimSpace(repoURL), "/")
	cachePath := c.cachePath(repoURL)
	if useCache {
		if blob, err := os.ReadFile(cachePath); err == nil {
			if ix, err := parseIndex(blob, repoURL); err == nil {
				return ix, nil
			}
		}
	}
	blob, err := c.get(ctx, repoURL)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(cachePath), 0o755); err == nil {
		_ = os.WriteFile(cachePath, append(blob, '\n'), 0o644)
	}
	return parseIndex(blob, repoURL)
}

func (c *Client) get(ctx context.Context, rawURL string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, err
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("FlashHub %s: HTTP %d", rawURL, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

func (c *Client) cachePath(repoURL string) string {
	sum := md5.Sum([]byte(repoURL))
	// sha-like key using md5 is fine for a cache filename; mirrors Python's short hash.
	return filepath.Join(c.CacheDir, hex.EncodeToString(sum[:])[:16]+".json")
}

func parseIndex(blob []byte, repoURL string) (*Index, error) {
	var payload indexResponse
	if err := json.Unmarshal(blob, &payload); err != nil {
		return nil, fmt.Errorf("FlashHub response is not JSON: %w", err)
	}
	if payload.Code != nil && *payload.Code != 0 {
		return nil, fmt.Errorf("FlashHub API error (code=%d): %s", *payload.Code, payload.Message)
	}
	ix := &Index{RepoURL: repoURL}
	for _, e := range payload.Data.Files {
		path := pathFromDownloadURL(e.DownloadURL)
		if path != "" && e.FileName != "" {
			if idx := strings.LastIndex(path, "/"); idx >= 0 {
				path = path[:idx+1] + e.FileName
			} else {
				path = e.FileName
			}
		} else if path == "" {
			path = e.FileName
		}
		if path == "" || strings.TrimSpace(e.DownloadURL) == "" {
			continue
		}
		f := File{Path: path, URL: e.DownloadURL, MD5: strings.ToLower(strings.TrimSpace(e.MD5Hash))}
		if e.FileSize != nil {
			f.Size = *e.FileSize
		}
		ix.Files = append(ix.Files, f)
	}
	if len(ix.Files) == 0 {
		return nil, fmt.Errorf("FlashHub repo %q returned no downloadable files", repoURL)
	}
	return ix, nil
}

func pathFromDownloadURL(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return ""
	}
	if m := cdnPathRe.FindStringSubmatch(u.Path); m != nil {
		decoded, _ := url.PathUnescape(m[1])
		return strings.Trim(decoded, "/")
	}
	decoded, _ := url.PathUnescape(u.Path)
	return strings.Trim(decoded, "/")
}

// DownloadFile fetches a repo file to dest, verifying MD5 when known.
func (c *Client) DownloadFile(ctx context.Context, f File, dest string, force, quiet bool) error {
	if !force {
		if info, err := os.Stat(dest); err == nil && !info.IsDir() {
			if f.MD5 == "" {
				return nil
			}
			if got, err := fileMD5(dest); err == nil && got == f.MD5 {
				return nil
			}
		}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, f.URL, nil)
	if err != nil {
		return err
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: HTTP %d", f.Path, resp.StatusCode)
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	tmp := dest + ".incomplete"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, resp.Body); err != nil {
		out.Close()
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	if f.MD5 != "" {
		got, err := fileMD5(tmp)
		if err != nil || got != f.MD5 {
			_ = os.Remove(tmp)
			return fmt.Errorf("MD5 mismatch for %s: expected %s, got %s", f.Path, f.MD5, got)
		}
	}
	return os.Rename(tmp, dest)
}

// DownloadManifest fetches flashcli-bundle.json from a repo into dest.
func (c *Client) DownloadManifest(ctx context.Context, repoURL, dest string, force, quiet bool) (map[string]any, error) {
	ix, err := c.FetchIndex(ctx, repoURL, true)
	if err != nil {
		return nil, err
	}
	entry := ix.Find(ManifestPath)
	if entry == nil {
		return nil, fmt.Errorf("No %s in FlashHub repo %q", ManifestPath, repoURL)
	}
	if err := c.DownloadFile(ctx, *entry, dest, force, quiet); err != nil {
		return nil, err
	}
	blob, err := os.ReadFile(dest)
	if err != nil {
		return nil, err
	}
	var data map[string]any
	if err := json.Unmarshal(blob, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func fileMD5(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// ErrNotFound is returned when a repo/file is absent.
var ErrNotFound = errors.New("flashhub: not found")

// SyncBundle downloads the bundle entry tree plus only the matching
// runtime/<envKey>/ cell into bundleDir, and returns the parsed manifest.
func (c *Client) SyncBundle(ctx context.Context, repoURL, bundleDir, envKey string, quiet bool) (map[string]any, error) {
	ix, err := c.FetchIndex(ctx, repoURL, true)
	if err != nil {
		return nil, err
	}
	manifestEntry := ix.Find(ManifestPath)
	if manifestEntry == nil {
		return nil, fmt.Errorf("No %s in FlashHub repo %q", ManifestPath, repoURL)
	}
	manifestDest := filepath.Join(bundleDir, ManifestPath)
	if err := c.DownloadFile(ctx, *manifestEntry, manifestDest, false, quiet); err != nil {
		return nil, err
	}
	blob, err := os.ReadFile(manifestDest)
	if err != nil {
		return nil, err
	}
	var manifest map[string]any
	if err := json.Unmarshal(blob, &manifest); err != nil {
		return nil, fmt.Errorf("parse %s: %w", ManifestPath, err)
	}

	for _, f := range ix.Files {
		if !WantFile(f.Path, envKey) {
			continue
		}
		dest := filepath.Join(bundleDir, filepath.FromSlash(f.Path))
		if err := c.DownloadFile(ctx, f, dest, false, quiet); err != nil {
			return nil, err
		}
	}
	return manifest, nil
}

// WantFile reports whether a repo-relative path should be synced: everything
// outside runtime/, plus only the matching runtime/<envKey>/ cell.
func WantFile(path, envKey string) bool {
	p := strings.Trim(path, "/")
	if !strings.HasPrefix(p, "runtime/") {
		return true
	}
	return strings.HasPrefix(p, "runtime/"+envKey+"/")
}

// MarkerName is the bundle sync marker filename.
const MarkerName = ".flashcli_bundle.json"

// WriteMarker writes the bundle sync marker under bundleDir from data.
func WriteMarker(bundleDir string, data map[string]any) error {
	blob, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(bundleDir, MarkerName), append(blob, '\n'), 0o644)
}
