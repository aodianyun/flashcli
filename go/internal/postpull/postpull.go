// Package postpull runs bundle manifest “post_pull“ steps (non-Hub assets).
// Mirrors flashcli_bundle/post_pull.py.
package postpull

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

const (
	// PaligemmaTokenizerMD5 is the expected digest of the PaliGemma tokenizer.
	PaligemmaTokenizerMD5 = "1420adc9856720a559e8a87284b195e2"
)

// PaligemmaTokenizerURL is the fixed PaliGemma SentencePiece model (var for tests).
var PaligemmaTokenizerURL = "https://storage.googleapis.com/big_vision/paligemma_tokenizer.model"

// HTTPClient is used for downloads; replaceable in tests.
var HTTPClient = http.DefaultClient

// DefaultPaligemmaPath returns $FLASH_RT_PALIGEMMA_TOKENIZER or the default cache.
func DefaultPaligemmaPath() string {
	if v := strings.TrimSpace(os.Getenv("FLASH_RT_PALIGEMMA_TOKENIZER")); v != "" {
		return expandHome(v)
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".cache", "flash_rt", "paligemma_tokenizer.model")
}

// PaligemmaReady reports whether dest exists with the expected MD5.
func PaligemmaReady(dest string) bool {
	if dest == "" {
		dest = DefaultPaligemmaPath()
	}
	got, err := fileMD5(dest)
	return err == nil && got == PaligemmaTokenizerMD5
}

// EnsurePaligemma downloads the tokenizer when missing/corrupt.
func EnsurePaligemma(ctx context.Context, dest string, quiet, force bool) (string, error) {
	if dest == "" {
		dest = DefaultPaligemmaPath()
	}
	if !force && PaligemmaReady(dest) {
		return dest, nil
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return "", err
	}
	tmp := dest + ".part"
	if err := download(ctx, PaligemmaTokenizerURL, tmp); err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	if got, _ := fileMD5(tmp); got != PaligemmaTokenizerMD5 {
		_ = os.Remove(tmp)
		return "", fmt.Errorf("PaliGemma tokenizer MD5 mismatch (expected %s, got %s)", PaligemmaTokenizerMD5, got)
	}
	if err := os.Rename(tmp, dest); err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	return dest, nil
}

// Run executes post_pull steps and returns env vars they set.
func Run(ctx context.Context, steps []any, quiet bool) ([]string, error) {
	var env []string
	for _, step := range steps {
		m, ok := step.(map[string]any)
		if !ok {
			continue
		}
		if tokenizer, _ := m["tokenizer"].(string); tokenizer == "paligemma" {
			path, err := EnsurePaligemma(ctx, "", quiet, false)
			if err != nil {
				return env, err
			}
			env = append(env, "FLASH_RT_PALIGEMMA_TOKENIZER="+path)
			continue
		}
	}
	return env, nil
}

func download(ctx context.Context, url, dest string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	resp, err := HTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: HTTP %d", url, resp.StatusCode)
	}
	out, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, resp.Body)
	return err
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

func expandHome(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(p, "~/"))
		}
	}
	return p
}
