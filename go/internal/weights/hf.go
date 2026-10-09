package weights

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/aodianyun/flashcli/go/internal/progress"
)

const (
	hfOfficialBase = "https://huggingface.co"
	hfMirrorBase   = "https://hf-mirror.com"
)

func hfBase(endpoint string) string {
	if endpoint == "" {
		return hfOfficialBase
	}
	return strings.TrimRight(endpoint, "/")
}

func hfRevision(rev string) string {
	if strings.TrimSpace(rev) == "" {
		return "main"
	}
	return rev
}

func hfAuthHeaders() http.Header {
	h := http.Header{}
	token := envOr("HF_TOKEN", "")
	if token == "" {
		token = envOr("HUGGING_FACE_HUB_TOKEN", "")
	}
	if token != "" {
		h.Set("Authorization", "Bearer "+token)
	}
	return h
}

// hfEndpointOrder mirrors Python download_endpoint_order. "" = official Hub.
func hfEndpointOrder(spec Spec) []string {
	if spec.Endpoint != "" {
		return []string{spec.Endpoint}
	}
	if env := strings.TrimRight(envOr("HF_ENDPOINT", ""), "/"); env != "" {
		return []string{env}
	}
	if envBool("FLASHCLI_PREFER_HF_MIRROR") && !envBool("FLASHCLI_NO_MIRROR") {
		return []string{hfMirrorBase, ""}
	}
	return []string{"", hfMirrorBase}
}

func hfReachable(ctx context.Context, base, repo, rev string) bool {
	cctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	url := base + "/api/models/" + repo + "/revision/" + rev
	req, err := http.NewRequestWithContext(cctx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	resp, err := HTTPClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}

func filterHFEndpoints(ctx context.Context, endpoints []string, repo, rev string, quiet bool) []string {
	if envBool("FLASHCLI_SKIP_HF_PROBE") {
		return endpoints
	}
	out := make([]string, 0, len(endpoints))
	for _, ep := range endpoints {
		if ep != "" {
			out = append(out, ep)
			continue
		}
		if hfReachable(ctx, hfOfficialBase, repo, rev) {
			out = append(out, ep)
		} else if !quiet {
			fmt.Fprintln(os.Stderr, "Skipping huggingface.co (unreachable); using mirror next ...")
		}
	}
	if len(out) > 0 {
		return out
	}
	return []string{hfMirrorBase}
}

type hfTreeEntry struct {
	Type string `json:"type"`
	Path string `json:"path"`
	Size int64  `json:"size"`
}

func listHFTree(ctx context.Context, base, repo, rev string, headers http.Header) ([]remoteFile, error) {
	url := base + "/api/models/" + repo + "/tree/" + rev + "?recursive=1"
	var files []remoteFile
	for url != "" {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
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
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			return nil, fmt.Errorf("list %s: HTTP %d", url, resp.StatusCode)
		}
		var entries []hfTreeEntry
		err = json.NewDecoder(resp.Body).Decode(&entries)
		next := linkNext(resp.Header.Get("Link"))
		resp.Body.Close()
		if err != nil {
			return nil, err
		}
		for _, e := range entries {
			if e.Type == "file" {
				files = append(files, remoteFile{Path: e.Path, Size: e.Size})
			}
		}
		url = next
	}
	return files, nil
}

func linkNext(header string) string {
	for _, part := range strings.Split(header, ",") {
		seg := strings.Split(part, ";")
		if len(seg) < 2 {
			continue
		}
		if !strings.Contains(seg[1], `rel="next"`) {
			continue
		}
		u := strings.TrimSpace(seg[0])
		u = strings.TrimPrefix(u, "<")
		u = strings.TrimSuffix(u, ">")
		return u
	}
	return ""
}

func hfResolveURL(base, repo, rev, path string) string {
	return base + "/" + repo + "/resolve/" + rev + "/" + path
}

func downloadHuggingFace(ctx context.Context, spec Spec, dest string, quiet bool) error {
	if spec.Repo == "" {
		return errors.New("HuggingFace weights spec requires non-empty 'repo'")
	}
	headers := hfAuthHeaders()
	rev := hfRevision(spec.Revision)
	endpoints := hfEndpointOrder(spec)
	if spec.Endpoint == "" && envOr("HF_ENDPOINT", "") == "" {
		endpoints = filterHFEndpoints(ctx, endpoints, spec.Repo, rev, quiet)
	}
	maxRetries := envInt("FLASHCLI_HF_DOWNLOAD_RETRIES", 3)
	if maxRetries < 1 {
		maxRetries = 1
	}

	var attempts []string
	for _, ep := range endpoints {
		base := hfBase(ep)
		label := ep
		if label == "" {
			label = hfOfficialBase
		}
		var last error
		for attempt := 0; attempt < maxRetries; attempt++ {
			last = hfDownloadOnce(ctx, base, spec, dest, headers, rev)
			if last == nil {
				return nil
			}
			if attempt+1 < maxRetries {
				if !quiet {
					fmt.Fprintf(os.Stderr, "HuggingFace download failed (%s), retry %d/%d in %s ...\n",
						label, attempt+2, maxRetries, retryDelay(attempt))
				}
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(retryDelay(attempt)):
				}
			}
		}
		attempts = append(attempts, fmt.Sprintf("  - %s: %v", label, last))
	}
	return fmt.Errorf("Failed to download HuggingFace repo %q -> %s\n  Attempts:\n%s\n"+
		"  Tip: export HF_ENDPOINT=https://hf-mirror.com before flashcli", spec.Repo, dest, strings.Join(attempts, "\n"))
}

func hfDownloadOnce(ctx context.Context, base string, spec Spec, dest string, headers http.Header, rev string) error {
	files, err := listHFTree(ctx, base, spec.Repo, rev, headers)
	if err != nil {
		return err
	}
	selected := filterFiles(files, spec.AllowPatterns)
	if len(spec.AllowPatterns) > 0 && len(selected) == 0 {
		return fmt.Errorf("no files in %s matched allow_patterns %v", spec.Repo, spec.AllowPatterns)
	}
	st := progress.Start("weights", spec.Repo)
	var _totalBytes int64
	for _, f := range selected {
		_totalBytes += f.Size
	}
	st.Totals(len(selected), _totalBytes)

	for _, f := range selected {
		target := dest + string(os.PathSeparator) + strings.ReplaceAll(f.Path, "/", string(os.PathSeparator))
		err := downloadFileWithResume(ctx, hfResolveURL(base, spec.Repo, rev, f.Path), target, f.Size, headers, st.Add)
		if err != nil {
			st.Done()
			return err
		}
		st.FileDone()
	}
	st.Done()
	if !weightsCacheReady(dest, spec) {
		return errors.New("Hub download completed but checkpoint files are missing")
	}
	return nil
}
