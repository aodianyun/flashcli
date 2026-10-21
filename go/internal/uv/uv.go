// Package uv locates or provisions the `uv` installer used for bundle venvs.
//
// uv is not shipped with flashcli releases: it is resolved from
// FLASHCLI_UV_BIN / PATH / a previously provisioned copy, and otherwise
// downloaded on demand from the configured PyPI index (CN mirror by default).
package uv

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/progress"
)

// MinVersion is the oldest uv accepted (uv venv/pip CLI we rely on).
const MinVersion = "0.5.0"

// HTTPClient is replaceable in tests.
var HTTPClient = &http.Client{}

// Version runs `uv --version` and returns the version token (e.g. "0.9.9").
func Version(ctx context.Context, bin string) (string, error) {
	out, err := exec.CommandContext(ctx, bin, "--version").Output()
	if err != nil {
		return "", err
	}
	fields := strings.Fields(string(out))
	if len(fields) < 2 {
		return "", fmt.Errorf("unexpected uv --version output: %q", strings.TrimSpace(string(out)))
	}
	return strings.TrimSpace(fields[1]), nil
}

// AtLeast reports whether version >= min (numeric semver; pre-releases sort low).
func AtLeast(version, min string) bool {
	a, okA := parse(version)
	b, okB := parse(min)
	if !okA || !okB {
		return false
	}
	for i := 0; i < 3; i++ {
		if a[i] != b[i] {
			return a[i] > b[i]
		}
	}
	return true
}

func parse(v string) ([3]int, bool) {
	var out [3]int
	v = strings.TrimPrefix(strings.TrimSpace(v), "v")
	// keep numeric leading components only
	parts := strings.Split(v, ".")
	if len(parts) < 2 {
		return out, false
	}
	for i := 0; i < 3 && i < len(parts); i++ {
		n, err := strconv.Atoi(leadingInt(parts[i]))
		if err != nil {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

func leadingInt(s string) string {
	end := 0
	for end < len(s) && s[end] >= '0' && s[end] <= '9' {
		end++
	}
	return s[:end]
}

// CacheDir is the uv cache root (co-located with runtimes for hardlinks and
// easy cleanup).
func CacheDir() string {
	if v := strings.TrimSpace(os.Getenv("UV_CACHE_DIR")); v != "" {
		return v
	}
	return filepath.Join(paths.Home(), "cache", "uv")
}

// Env returns uv environment overrides (only when not already set).
func Env() []string {
	var out []string
	if strings.TrimSpace(os.Getenv("UV_CACHE_DIR")) == "" {
		out = append(out, "UV_CACHE_DIR="+CacheDir())
	}
	if strings.TrimSpace(os.Getenv("UV_LINK_MODE")) == "" {
		out = append(out, "UV_LINK_MODE=hardlink")
	}
	// `uv venv --seed` and default installs should honour the configured PyPI
	// mirror (explicit --index-url args still take precedence).
	if strings.TrimSpace(os.Getenv("UV_INDEX_URL")) == "" {
		if idx := strings.TrimSpace(os.Getenv("PIP_INDEX_URL")); idx != "" {
			out = append(out, "UV_INDEX_URL="+idx)
		}
	}
	return out
}

// Ensure resolves a usable uv binary, provisioning one when allowed.
func Ensure(ctx context.Context, quiet, autoInstall bool) (string, error) {
	if bin := strings.TrimSpace(os.Getenv("FLASHCLI_UV_BIN")); bin != "" {
		if err := check(ctx, bin); err != nil {
			return "", fmt.Errorf("FLASHCLI_UV_BIN=%s: %w", bin, err)
		}
		return bin, nil
	}
	if bin, err := exec.LookPath("uv"); err == nil {
		if err := check(ctx, bin); err == nil {
			return bin, nil
		}
	}
	if bin, ok := provisioned(); ok {
		if err := check(ctx, bin); err == nil {
			return bin, nil
		}
	}
	if !autoInstall || envFalse("FLASHCLI_UV_AUTO_INSTALL") {
		return "", fmt.Errorf("uv not found (set FLASHCLI_UV_BIN, install uv, or allow auto-install)")
	}
	ver := strings.TrimSpace(os.Getenv("FLASHCLI_UV_VERSION"))
	if ver == "" {
		ver = latestVersion(ctx, quiet)
	}
	if ver == "" {
		return "", fmt.Errorf("cannot resolve a uv version from the PyPI index (set FLASHCLI_UV_VERSION or FLASHCLI_UV_BIN)")
	}
	return Provision(ctx, ver, quiet)
}

func check(ctx context.Context, bin string) error {
	v, err := Version(ctx, bin)
	if err != nil {
		return err
	}
	if !AtLeast(v, MinVersion) {
		return fmt.Errorf("uv %s is older than required %s", v, MinVersion)
	}
	return nil
}

func envFalse(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "0", "false", "no", "off":
		return true
	}
	return false
}

func toolsDir(version string) string {
	return filepath.Join(paths.Home(), "tools", "uv", version)
}

// provisioned returns the newest provisioned uv >= MinVersion.
func provisioned() (string, bool) {
	root := filepath.Join(paths.Home(), "tools", "uv")
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", false
	}
	var versions []string
	for _, e := range entries {
		if e.IsDir() && AtLeast(e.Name(), MinVersion) {
			versions = append(versions, e.Name())
		}
	}
	if len(versions) == 0 {
		return "", false
	}
	sort.Slice(versions, func(i, j int) bool { return versionLess(versions[i], versions[j]) })
	bin := filepath.Join(root, versions[len(versions)-1], "uv")
	if info, err := os.Stat(bin); err == nil && !info.IsDir() {
		return bin, true
	}
	return "", false
}

func versionLess(a, b string) bool {
	x, _ := parse(a)
	y, _ := parse(b)
	for i := 0; i < 3; i++ {
		if x[i] != y[i] {
			return x[i] < y[i]
		}
	}
	return false
}

// --- PyPI simple index ------------------------------------------------

var hrefRe = regexp.MustCompile(`href="([^"]+)"`)
var wheelRe = regexp.MustCompile(`^uv-(\d+\.\d+\.\d+)-py3-none-(.+)\.whl$`)

type wheel struct {
	version string
	url     string
	sha256  string
}

func indexURL() string {
	if v := strings.TrimSpace(os.Getenv("PIP_INDEX_URL")); v != "" {
		return v
	}
	return mirror.DefaultPipIndexURL
}

func platformMatch(tag string) bool {
	switch runtime.GOARCH {
	case "amd64":
		return strings.Contains(tag, "x86_64") && strings.Contains(tag, "manylinux")
	case "arm64":
		return strings.Contains(tag, "aarch64") && strings.Contains(tag, "manylinux")
	default:
		return false
	}
}

// wheels fetches and parses the uv project page of the simple index.
func wheels(ctx context.Context) ([]wheel, error) {
	base := indexURL()
	if !strings.HasSuffix(base, "/") {
		base += "/"
	}
	page := base + "uv/"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, page, nil)
	if err != nil {
		return nil, err
	}
	resp, err := HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetch %s: HTTP %d", page, resp.StatusCode)
	}
	blob, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	baseURL, err := url.Parse(page)
	if err != nil {
		return nil, err
	}
	var out []wheel
	for _, m := range hrefRe.FindAllStringSubmatch(string(blob), -1) {
		ref := strings.TrimSpace(m[1])
		u, err := url.Parse(ref)
		if err != nil {
			continue
		}
		sum := ""
		if frag := u.Fragment; strings.HasPrefix(frag, "sha256=") {
			sum = strings.TrimPrefix(frag, "sha256=")
			u.Fragment = ""
		}
		name := filepath.Base(u.Path)
		wm := wheelRe.FindStringSubmatch(name)
		if wm == nil || !platformMatch(wm[2]) {
			continue
		}
		out = append(out, wheel{version: wm[1], url: baseURL.ResolveReference(u).String(), sha256: sum})
	}
	return out, nil
}

func latestVersion(ctx context.Context, quiet bool) string {
	ws, err := wheels(ctx)
	if err != nil {
		if !quiet {
			progress.Warn("uv: cannot query %s: %v", indexURL(), err)
		}
		return ""
	}
	var versions []string
	seen := map[string]bool{}
	for _, w := range ws {
		if !seen[w.version] && AtLeast(w.version, MinVersion) {
			seen[w.version] = true
			versions = append(versions, w.version)
		}
	}
	if len(versions) == 0 {
		return ""
	}
	sort.Slice(versions, func(i, j int) bool { return versionLess(versions[i], versions[j]) })
	return versions[len(versions)-1]
}

// Provision downloads uv <version> from the PyPI index and extracts the binary.
func Provision(ctx context.Context, version string, quiet bool) (string, error) {
	version = strings.TrimPrefix(strings.TrimSpace(version), "v")
	ws, err := wheels(ctx)
	if err != nil {
		return "", err
	}
	var chosen *wheel
	for i := range ws {
		if ws[i].version == version {
			chosen = &ws[i]
			break
		}
	}
	if chosen == nil {
		return "", fmt.Errorf("uv %s not found on %s for %s/%s", version, indexURL(), runtime.GOOS, runtime.GOARCH)
	}
	if chosen.sha256 == "" {
		return "", fmt.Errorf("uv %s wheel has no sha256 in the index", version)
	}
	if !quiet {
		progress.Note("uv: provisioning %s from %s", version, indexURL())
	}
	tmp, err := os.CreateTemp("", "uv-*.whl")
	if err != nil {
		return "", err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := download(ctx, chosen.url, tmp); err != nil {
		tmp.Close()
		return "", err
	}
	if err := tmp.Close(); err != nil {
		return "", err
	}
	if err := verifyFile(tmpName, chosen.sha256); err != nil {
		return "", err
	}
	bin, err := extractBinary(tmpName, toolsDir(version))
	if err != nil {
		return "", err
	}
	if !quiet {
		progress.Note("uv: installed %s", bin)
	}
	return bin, nil
}

func download(ctx context.Context, rawURL string, w io.Writer) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	resp, err := HTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: HTTP %d", rawURL, resp.StatusCode)
	}
	_, err = io.Copy(w, resp.Body)
	return err
}

func verifyFile(path, wantHex string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	got := hex.EncodeToString(h.Sum(nil))
	if !strings.EqualFold(got, wantHex) {
		return fmt.Errorf("uv wheel checksum mismatch: got %s want %s", got, wantHex)
	}
	return nil
}

func extractBinary(wheelPath, destDir string) (string, error) {
	zr, err := zip.OpenReader(wheelPath)
	if err != nil {
		return "", err
	}
	defer zr.Close()
	var entry *zip.File
	for _, f := range zr.File {
		name := filepath.ToSlash(f.Name)
		if strings.HasSuffix(name, ".data/scripts/uv") || filepath.Base(name) == "uv" {
			entry = f
			break
		}
	}
	if entry == nil {
		return "", fmt.Errorf("uv binary not found in wheel")
	}
	if err := os.MkdirAll(destDir, 0o755); err != nil {
		return "", err
	}
	rc, err := entry.Open()
	if err != nil {
		return "", err
	}
	defer rc.Close()
	dest := filepath.Join(destDir, "uv")
	tmp := dest + ".tmp"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(out, rc); err != nil {
		out.Close()
		os.Remove(tmp)
		return "", err
	}
	if err := out.Close(); err != nil {
		os.Remove(tmp)
		return "", err
	}
	if err := os.Chmod(tmp, 0o755); err != nil {
		os.Remove(tmp)
		return "", err
	}
	if err := os.Rename(tmp, dest); err != nil {
		os.Remove(tmp)
		return "", err
	}
	return dest, nil
}
