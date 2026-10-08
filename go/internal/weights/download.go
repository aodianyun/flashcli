// Package weights downloads model weights into the flashcli cache.
//
// It mirrors the host-only behaviour of src/flashcli/models/{pull,hf_hub,ms_hub}.py
// while replacing the Hugging Face CLI / Python ModelScope SDK with native Go
// HTTP clients (see docs/host_go_migration.md section on weights).
package weights

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// HTTPClient is used for all downloads; replaceable in tests.
var HTTPClient = &http.Client{}

type remoteFile struct {
	Path string
	Size int64
}

// Download fetches spec into dest, resuming partial downloads. It is a no-op
// when the destination already satisfies the spec's readiness rules.
func Download(ctx context.Context, spec Spec, dest string, quiet bool) error {
	if dest == "" {
		return errors.New("weights: empty destination")
	}
	if weightsCacheReady(dest, spec) {
		if !quiet {
			fmt.Fprintf(os.Stderr, "Weights already cached: %s\n", dest)
		}
		return nil
	}
	if err := prepareDest(dest, quiet, spec); err != nil {
		return err
	}
	switch spec.Source {
	case "huggingface":
		return downloadHuggingFace(ctx, spec, dest, quiet)
	case "modelscope":
		return downloadModelScope(ctx, spec, dest, quiet)
	case "bundled":
		return copyBundled(spec, dest, quiet)
	case "url":
		return errors.New("weights.source=url is reserved; use huggingface or modelscope repo")
	default:
		return fmt.Errorf("Unsupported weights source: %q", spec.Source)
	}
}

// weightsCacheReady mirrors Python _weights_cache_ready.
func weightsCacheReady(dest string, spec Spec) bool {
	if len(spec.RequireAnyPatterns) > 0 || spec.CheckpointSubdir != "" {
		return ExtraWeightsReady(dest, spec)
	}
	return HasCachedWeightFiles(dest, spec.AllowPatterns, spec.RequireNormStats)
}

func prepareDest(dest string, quiet bool, spec Spec) error {
	if !isDir(dest) {
		return os.MkdirAll(dest, 0o755)
	}
	entries, err := os.ReadDir(dest)
	if err != nil {
		return err
	}
	if len(entries) > 0 && !quiet {
		hub := "HuggingFace"
		if spec.Source == "modelscope" {
			hub = "ModelScope"
		}
		fmt.Fprintf(os.Stderr, "Resuming incomplete %s download (%d cached entries): %s\n", hub, len(entries), dest)
	}
	return nil
}

func copyBundled(spec Spec, dest string, quiet bool) error {
	rel := strings.Trim(strings.TrimSpace(spec.RelativeDir), "/")
	root, _ := spec.Raw["_bundle_root"].(string)
	if rel == "" || root == "" {
		return errors.New("bundled weights spec requires relative_dir and _bundle_root")
	}
	src := filepath.Join(root, filepath.FromSlash(rel))
	if !isDir(src) {
		return fmt.Errorf("Bundled weights missing under bundle: %s", src)
	}
	if ExtraWeightsReady(dest, spec) {
		return nil
	}
	copied := 0
	err := filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		sub, relErr := filepath.Rel(src, path)
		if relErr != nil {
			return relErr
		}
		if strings.HasPrefix(filepath.ToSlash(sub), ".cache/") {
			return nil
		}
		target := filepath.Join(dest, sub)
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		if err := copyFile(path, target); err != nil {
			return err
		}
		copied++
		return nil
	})
	if err != nil {
		return err
	}
	if copied == 0 {
		return fmt.Errorf("No files to copy from bundled weights: %s", src)
	}
	if !ExtraWeightsReady(dest, spec) {
		return fmt.Errorf("Bundled weights incomplete after copy %s -> %s", src, dest)
	}
	return nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Sync()
}

// downloadFileWithResume downloads url to destPath, resuming a .incomplete file.
func downloadFileWithResume(ctx context.Context, url, destPath string, size int64, headers http.Header) error {
	if info, err := os.Stat(destPath); err == nil && size > 0 && info.Size() == size {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(destPath), 0o755); err != nil {
		return err
	}
	tmp := destPath + ".incomplete"
	start := int64(0)
	if info, err := os.Stat(tmp); err == nil {
		start = info.Size()
		if size > 0 && start >= size {
			if start == size {
				return os.Rename(tmp, destPath)
			}
			_ = os.Remove(tmp)
			start = 0
		}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	for k, vs := range headers {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	if start > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", start))
	}
	resp, err := HTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusOK:
		start = 0
	case http.StatusPartialContent:
	case http.StatusRequestedRangeNotSatisfiable:
		if size > 0 && start == size {
			return os.Rename(tmp, destPath)
		}
		_ = os.Remove(tmp)
		return fmt.Errorf("range not satisfiable for %s", url)
	default:
		return fmt.Errorf("download %s: HTTP %d", url, resp.StatusCode)
	}

	flags := os.O_CREATE | os.O_WRONLY
	if start > 0 {
		flags |= os.O_APPEND
	} else {
		flags |= os.O_TRUNC
	}
	out, err := os.OpenFile(tmp, flags, 0o644)
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
	return os.Rename(tmp, destPath)
}

func filterFiles(files []remoteFile, patterns []string) []remoteFile {
	if len(patterns) == 0 {
		return files
	}
	out := make([]remoteFile, 0, len(files))
	for _, f := range files {
		for _, pat := range patterns {
			if matchPattern(f.Path, pat) {
				out = append(out, f)
				break
			}
		}
	}
	return out
}

func envOr(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func envBool(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

func retryDelay(attempt int) time.Duration {
	base := envInt("FLASHCLI_HF_RETRY_DELAY", 5)
	d := time.Duration(base*(attempt+1)) * time.Second
	if d > 60*time.Second {
		d = 60 * time.Second
	}
	return d
}
