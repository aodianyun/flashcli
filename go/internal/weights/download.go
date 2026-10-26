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

// Download fetches spec into dest, resuming partial downloads.
//
// Two independent concerns:
//   - host download completeness: the per-destination manifest
//     (.flashcli_download.json) records the expected remote file set; the cache
//     is complete only when every file is present with its size;
//   - bundle readiness: bundleWeightsReady applies flashcli-bundle.json rules.
//
// verifyRemote is true only for an explicit pull: it forces a remote listing so
// completeness is verified and the manifest is (re)written. run/serve pass
// false: when a manifest exists the check is local-only, and a legacy cache
// (no manifest) that satisfies the bundle's declared readiness is accepted
// without touching the network — so a completed pull always runs offline.
func Download(ctx context.Context, spec Spec, dest string, quiet, verifyRemote bool) error {
	if dest == "" {
		return errors.New("weights: empty destination")
	}
	switch spec.Source {
	case "huggingface", "modelscope":
		return downloadRemote(ctx, spec, dest, quiet, verifyRemote, func(relist bool) error {
			if spec.Source == "modelscope" {
				return downloadModelScope(ctx, spec, dest, quiet, relist)
			}
			return downloadHuggingFace(ctx, spec, dest, quiet, relist)
		})
	case "bundled":
		if bundleWeightsReady(dest, spec) {
			if !quiet {
				fmt.Fprintf(os.Stderr, "Weights already cached: %s\n", dest)
			}
			return nil
		}
		if err := prepareDest(dest, quiet, spec); err != nil {
			return err
		}
		return copyBundled(spec, dest, quiet)
	case "url":
		return errors.New("weights.source=url is reserved; use huggingface or modelscope repo")
	default:
		return fmt.Errorf("Unsupported weights source: %q", spec.Source)
	}
}

// downloadRemote enforces host completeness and bundle readiness separately.
const incompleteMarker = ".flashcli_download.incomplete"

func downloadRemote(ctx context.Context, spec Spec, dest string, quiet, verifyRemote bool, download func(relist bool) error) error {
	man, hasManifest := readDownloadManifest(dest, spec.Repo)
	marker := filepath.Join(dest, incompleteMarker)
	// A manifest file that cannot be parsed (or belongs to another repo) must
	// not be mistaken for a legacy cache: force a fresh listing.
	manifestPresent := fileExists(downloadManifestPath(dest))
	// An explicit pull re-lists the remote even when the local manifest is
	// complete, so upstream changes are picked up.
	if hasManifest && !verifyRemote {
		if len(manifestMissing(dest, manifestFiles(man))) == 0 {
			if !bundleWeightsReady(dest, spec) {
				return fmt.Errorf("bundle weight requirements not met in %s: check require_norm_stats / allow_patterns / require_any_patterns against the downloaded files", dest)
			}
			_ = os.Remove(marker)
			if !quiet {
				fmt.Fprintf(os.Stderr, "Weights already cached: %s\n", dest)
			}
			return nil
		}
		// Manifest present but incomplete: the download did not complete.
	} else if !hasManifest && !manifestPresent && !verifyRemote && !fileExists(marker) && bundleWeightsReady(dest, spec) {
		// Legacy cache (pre-manifest) on run/serve: accept locally, no network.
		// An interrupted download leaves incompleteMarker, so it is never
		// mistaken for a legacy ready cache.
		if !quiet {
			fmt.Fprintf(os.Stderr, "Weights already cached (bundle readiness; no download manifest): %s\n", dest)
		}
		return nil
	}
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(marker, []byte("incomplete\n"), 0o644); err != nil {
		return err
	}
	if err := download(verifyRemote); err != nil {
		return err
	}
	if !bundleWeightsReady(dest, spec) {
		// The download itself may be complete while the bundle's readiness
		// rules fail; the marker describes download state, so clear it.
		if man, ok := readDownloadManifest(dest, spec.Repo); ok && len(manifestMissing(dest, manifestFiles(man))) == 0 {
			_ = os.Remove(marker)
		}
		return fmt.Errorf("bundle weight requirements not met in %s: check require_norm_stats / allow_patterns / require_any_patterns against the downloaded files", dest)
	}
	_ = os.Remove(marker)
	return nil
}

// bundleWeightsReady is the bundle-side readiness check: it applies rules
// declared in flashcli-bundle.json. It is NOT the download-completeness check.
func bundleWeightsReady(dest string, spec Spec) bool {
	if len(spec.RequireAnyPatterns) > 0 || spec.CheckpointSubdir != "" {
		return ExtraWeightsReady(dest, spec)
	}
	return HasCachedWeightFiles(dest, spec.AllowPatterns, spec.RequireNormStats)
}

// IsCached reports whether dest is already usable for spec without touching the
// network. It mirrors the local checks in downloadRemote: incomplete downloads,
// partial/corrupt/foreign manifests, and failed bundle readiness are not cached;
// a legacy cache (no manifest, no incomplete marker) is accepted when it
// satisfies the bundle's readiness rules.
func IsCached(dest string, spec Spec) bool {
	if dest == "" || !isDir(dest) {
		return false
	}
	if fileExists(filepath.Join(dest, incompleteMarker)) {
		return false
	}
	if man, ok := readDownloadManifest(dest, spec.Repo); ok {
		if len(manifestMissing(dest, manifestFiles(man))) != 0 {
			return false
		}
		return bundleWeightsReady(dest, spec)
	}
	// A manifest that cannot be parsed or belongs to another repo must force a
	// fresh listing; it is not a legacy cache.
	if fileExists(downloadManifestPath(dest)) {
		return false
	}
	return bundleWeightsReady(dest, spec)
}

func prepareDest(dest string, quiet bool, spec Spec) error {
	if !isDir(dest) {
		return os.MkdirAll(dest, 0o755)
	}
	entries, err := os.ReadDir(dest)
	if err != nil {
		return err
	}
	count := 0
	for _, e := range entries {
		switch e.Name() {
		case downloadManifestName, incompleteMarker:
			continue
		}
		count++
	}
	if count > 0 && !quiet {
		hub := "HuggingFace"
		if spec.Source == "modelscope" {
			hub = "ModelScope"
		}
		fmt.Fprintf(os.Stderr, "Resuming incomplete %s download (%d cached entries): %s\n", hub, count, dest)
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
// onBytes (optional) receives transferred byte counts for progress.
func downloadFileWithResume(ctx context.Context, url, destPath string, size int64, headers http.Header, onBytes func(int)) error {
	// Zero-byte hub markers (e.g. HuggingFace SUCCESS) need no network; a
	// 429 on them must not abort the whole download.
	if size == 0 {
		if info, err := os.Stat(destPath); err == nil && info.Size() == 0 {
			return nil
		}
		if err := os.MkdirAll(filepath.Dir(destPath), 0o755); err != nil {
			return err
		}
		_ = os.Remove(destPath + ".incomplete")
		return os.WriteFile(destPath, nil, 0o644)
	}
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
	if start > 0 && onBytes != nil {
		onBytes(int(start))
	}
	buf := make([]byte, 1<<20)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := out.Write(buf[:n]); werr != nil {
				out.Close()
				return werr
			}
			if onBytes != nil {
				onBytes(n)
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			out.Close()
			return rerr
		}
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
