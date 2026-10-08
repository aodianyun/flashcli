// Package selfupdate downloads, verifies and atomically installs a new
// flashcli-go binary. Mirrors the release/checksum model of scripts/release_*.
package selfupdate

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// AssetName is the release artifact filename for a platform.
func AssetName(goos, goarch string) string {
	return fmt.Sprintf("flashcli-%s-%s", goos, goarch)
}

// ParseChecksums parses "<hex>  <name>" lines (sha256sum format).
func ParseChecksums(text string) map[string]string {
	out := map[string]string{}
	for _, line := range strings.Split(text, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		name := strings.TrimPrefix(fields[len(fields)-1], "*")
		out[name] = strings.ToLower(fields[0])
	}
	return out
}

// Verify checks data against an expected lowercase hex sha256.
func Verify(data []byte, wantHex string) error {
	wantHex = strings.ToLower(strings.TrimSpace(wantHex))
	if wantHex == "" {
		return errors.New("empty expected checksum")
	}
	sum := sha256.Sum256(data)
	got := hex.EncodeToString(sum[:])
	if got != wantHex {
		return fmt.Errorf("checksum mismatch: got %s want %s", got, wantHex)
	}
	return nil
}

// Download fetches a URL into memory.
func Download(ctx context.Context, client *http.Client, url string) ([]byte, error) {
	if client == nil {
		client = http.DefaultClient
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download %s: HTTP %d", url, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

// Replace atomically installs data as target, preserving the executable bit.
func Replace(target string, data []byte) error {
	dir := filepath.Dir(target)
	tmp, err := os.CreateTemp(dir, ".flashcli-update-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, 0o755); err != nil {
		return err
	}
	return os.Rename(tmpName, target)
}

// Executable returns the resolved path of the running binary (symlinks resolved).
func Executable() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	resolved, err := filepath.EvalSymlinks(exe)
	if err != nil {
		return exe, nil
	}
	return resolved, nil
}

type releaseInfo struct {
	TagName string `json:"tag_name"`
	Name    string `json:"name"`
}

// LatestVersion queries a GitHub-compatible releases API and returns the tag
// with a leading "v" stripped.
func LatestVersion(ctx context.Context, client *http.Client, apiURL string) (string, error) {
	blob, err := Download(ctx, client, apiURL)
	if err != nil {
		return "", err
	}
	var info releaseInfo
	if err := json.Unmarshal(blob, &info); err != nil {
		return "", fmt.Errorf("parse release JSON: %w", err)
	}
	tag := strings.TrimSpace(info.TagName)
	if tag == "" {
		tag = strings.TrimSpace(info.Name)
	}
	if tag == "" {
		return "", errors.New("release JSON has no tag_name")
	}
	return strings.TrimPrefix(tag, "v"), nil
}

// ReleaseURL joins a base URL, version and asset name.
func ReleaseURL(base, version, asset string) string {
	return strings.TrimRight(base, "/") + "/v" + strings.TrimPrefix(version, "v") + "/" + asset
}
