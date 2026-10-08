package weights

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const msOfficialBase = "https://www.modelscope.cn"

func msBase(spec Spec) string {
	if spec.Endpoint != "" {
		return strings.TrimRight(spec.Endpoint, "/")
	}
	if env := strings.TrimRight(envOr("MODELSCOPE_ENDPOINT", ""), "/"); env != "" {
		return env
	}
	return msOfficialBase
}

// msRevisionAttempts mirrors Python modelscope_revision_attempts ("" = default).
func msRevisionAttempts(rev string) []string {
	rev = strings.TrimSpace(rev)
	if rev == "" {
		return []string{""}
	}
	if strings.EqualFold(rev, "main") {
		return []string{"master", ""}
	}
	return []string{rev, ""}
}

func msAuthHeaders() http.Header {
	h := http.Header{}
	if token := envOr("MODELSCOPE_API_TOKEN", ""); token != "" {
		h.Set("Authorization", "Bearer "+token)
	}
	return h
}

type msFile struct {
	Name string `json:"Name"`
	Path string `json:"Path"`
	Type string `json:"Type"`
	Size int64  `json:"Size"`
}

type msListResponse struct {
	Code int    `json:"Code"`
	Msg  string `json:"Message"`
	Data struct {
		Files []msFile `json:"Files"`
	} `json:"Data"`
}

type msRevisionNotFound struct{ repo, rev string }

func (e *msRevisionNotFound) Error() string {
	return fmt.Sprintf("ModelScope revision %q not found for %q", e.rev, e.repo)
}

func msListFiles(ctx context.Context, base, repo, rev string, headers http.Header) ([]remoteFile, error) {
	seen := map[string]bool{}
	var out []remoteFile
	for page := 1; ; page++ {
		q := url.Values{}
		if rev != "" {
			q.Set("Revision", rev)
		}
		q.Set("PageNumber", strconv.Itoa(page))
		q.Set("PageSize", "1000")
		reqURL := base + "/api/v1/models/" + repo + "/repo/files?" + q.Encode()
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
		if err != nil {
			return nil, err
		}
		for k, vs := range headers {
			for _, v := range vs {
				req.Header.Add(k, v)
			}
		}
		resp, err := HTTPClient.Do(req)
		if err != nil {
			return nil, err
		}
		if resp.StatusCode == http.StatusNotFound {
			resp.Body.Close()
			return nil, &msRevisionNotFound{repo: repo, rev: rev}
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			return nil, fmt.Errorf("list %s: HTTP %d", reqURL, resp.StatusCode)
		}
		var payload msListResponse
		err = json.NewDecoder(resp.Body).Decode(&payload)
		resp.Body.Close()
		if err != nil {
			return nil, err
		}
		if payload.Code != 0 && payload.Code != 200 {
			return nil, fmt.Errorf("ModelScope list failed for %q: code %d %s", repo, payload.Code, payload.Msg)
		}
		added := 0
		for _, f := range payload.Data.Files {
			if f.Type != "blob" || seen[f.Path] {
				continue
			}
			seen[f.Path] = true
			out = append(out, remoteFile{Path: f.Path, Size: f.Size})
			added++
		}
		if added == 0 {
			break
		}
	}
	return out, nil
}

func msResolveURL(base, repo, rev, path string) string {
	q := url.Values{}
	if rev != "" {
		q.Set("Revision", rev)
	}
	q.Set("FilePath", path)
	return base + "/api/v1/models/" + repo + "/repo?" + q.Encode()
}

func downloadModelScope(ctx context.Context, spec Spec, dest string, quiet bool) error {
	if spec.Repo == "" {
		return errors.New("ModelScope weights spec requires non-empty 'repo'")
	}
	base := msBase(spec)
	headers := msAuthHeaders()
	maxRetries := envInt("FLASHCLI_MS_DOWNLOAD_RETRIES", 3)
	if maxRetries < 1 {
		maxRetries = 1
	}

	var attempts []string
	for _, rev := range msRevisionAttempts(spec.Revision) {
		var last error
		revNotFound := false
		for attempt := 0; attempt < maxRetries; attempt++ {
			last = msDownloadOnce(ctx, base, spec, dest, headers, rev)
			if last == nil {
				return nil
			}
			var notFound *msRevisionNotFound
			if errors.As(last, &notFound) {
				revNotFound = true
				break
			}
			if attempt+1 < maxRetries {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(retryDelay(attempt)):
				}
			}
		}
		label := rev
		if label == "" {
			label = "(default)"
		}
		attempts = append(attempts, fmt.Sprintf("  - %s revision=%s: %v", base, label, last))
		if revNotFound {
			continue
		}
		break
	}
	return fmt.Errorf("Failed to download ModelScope model %q -> %s\n  Attempts:\n%s",
		spec.Repo, dest, strings.Join(attempts, "\n"))
}

func msDownloadOnce(ctx context.Context, base string, spec Spec, dest string, headers http.Header, rev string) error {
	files, err := msListFiles(ctx, base, spec.Repo, rev, headers)
	if err != nil {
		return err
	}
	selected := filterFiles(files, spec.AllowPatterns)
	if len(spec.AllowPatterns) > 0 && len(selected) == 0 {
		return fmt.Errorf("no files in %s matched allow_patterns %v", spec.Repo, spec.AllowPatterns)
	}
	for _, f := range selected {
		target := dest + string(os.PathSeparator) + strings.ReplaceAll(f.Path, "/", string(os.PathSeparator))
		if err := downloadFileWithResume(ctx, msResolveURL(base, spec.Repo, rev, f.Path), target, f.Size, headers); err != nil {
			return err
		}
	}
	if !weightsCacheReady(dest, spec) {
		return errors.New("ModelScope download completed but checkpoint files are missing")
	}
	return nil
}
