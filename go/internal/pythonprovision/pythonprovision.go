// Package pythonprovision resolves (and optionally installs) the interpreter a
// bundle needs, mirroring src/flashcli/bundle/python_install.py:
// env override -> provisioned standalone -> system python -> auto-install from
// the FlashHub python-standalone repo.
package pythonprovision

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

// DefaultStandaloneTag mirrors standalone_release.DEFAULT_STANDALONE_TAG.
var DefaultStandaloneTag = "20260602"

const manifestName = "python-standalone.json"

// HTTPClient is used for tarball downloads; replaceable in tests.
var HTTPClient = http.DefaultClient

var envLoaded bool

// Root is the user-writable prefix for standalone Python.
func Root() string {
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_ROOT")); v != "" {
		return expandHome(v)
	}
	return filepath.Join(paths.Home(), "python")
}

// EnvFile is the generated python-runtime.env path.
func EnvFile() string {
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_ENV")); v != "" {
		return expandHome(v)
	}
	return filepath.Join(paths.Home(), "python-runtime.env")
}

// LoadEnvFile loads FLASHCLI_PY*_BIN from EnvFile without overriding the env.
func LoadEnvFile() {
	if envLoaded {
		return
	}
	envLoaded = true
	blob, err := os.ReadFile(EnvFile())
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(blob), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		eq := strings.IndexByte(line, '=')
		if eq < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eq])
		val := strings.Trim(strings.TrimSpace(line[eq+1:]), `"'`)
		if strings.HasPrefix(key, "FLASHCLI_PY") && strings.HasSuffix(key, "_BIN") && val != "" {
			os.Setenv(key, val)
		}
	}
}

// Enabled reports whether auto-install is allowed.
func Enabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON"))) {
	case "0", "false", "no", "off":
		return false
	}
	return true
}

// Triplet returns the python-build-standalone target triple.
func Triplet() (string, error) {
	machine := strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_TEST_MACHINE")))
	if machine == "" {
		machine = runtime.GOARCH
	}
	switch {
	case machine == "amd64" || machine == "x86_64":
		return "x86_64-unknown-linux-gnu", nil
	case machine == "arm64" || machine == "aarch64":
		return "aarch64-unknown-linux-gnu", nil
	}
	return "", fmt.Errorf("Standalone Python install is not supported on this platform (%s)", machine)
}

func mm(abi string) string { return abi[0:1] + "." + abi[1:] }

// Resolve returns an interpreter path for abi ("312"), or ("", false).
func Resolve(abi string) (string, bool) {
	LoadEnvFile()
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PY" + abi + "_BIN")); v != "" {
		if reportsMinor(v, abi) {
			return v, true
		}
		return v, true
	}
	provisioned := filepath.Join(Root(), mm(abi), "bin")
	for _, name := range []string{"python" + mm(abi), "python3", "python"} {
		candidate := filepath.Join(provisioned, name)
		if isExecutable(candidate) && reportsMinor(candidate, abi) {
			return candidate, true
		}
	}
	for _, name := range []string{"python" + mm(abi), "python3." + abi[1:]} {
		if p, err := exec.LookPath(name); err == nil && reportsMinor(p, abi) {
			return p, true
		}
	}
	return "", false
}

// Ensure resolves or (when allowed) installs the interpreter.
func Ensure(ctx context.Context, abi string, autoInstall, quiet bool) (string, bool, error) {
	if p, ok := Resolve(abi); ok {
		return p, true, nil
	}
	if !autoInstall || !Enabled() {
		return "", false, nil
	}
	p, err := InstallStandalone(ctx, abi, quiet)
	if err != nil {
		return "", false, err
	}
	return p, true, nil
}

var versionInfoRe = regexp.MustCompile(`\((\d+),\s*(\d+)\)`)

func reportsMinor(pyBin, abi string) bool {
	out, err := exec.Command(pyBin, "-c", "import sys; print(sys.version_info[:2])").Output()
	if err != nil {
		return false
	}
	m := versionInfoRe.FindStringSubmatch(string(out))
	if m == nil {
		return false
	}
	return m[1] == abi[0:1] && m[2] == abi[1:]
}

func isExecutable(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir() && info.Mode()&0o111 != 0
}

// Asset is a resolved standalone tarball.
type Asset struct {
	PyMinor  string
	Triplet  string
	Tag      string
	Filename string
	URL      string
	MD5      string
}

type manifestFile struct {
	PyMinor  string `json:"py_minor"`
	Triplet  string `json:"triplet"`
	Tag      string `json:"tag"`
	Path     string `json:"path"`
	Filename string `json:"filename"`
	URL      string `json:"url"`
	MD5      string `json:"md5"`
}

type standaloneManifest struct {
	Files []manifestFile `json:"files"`
}

// ResolveAsset resolves a tarball via explicit URL, local manifest, or FlashHub.
func ResolveAsset(ctx context.Context, abi, triplet, tag, repoURL string) (Asset, error) {
	if url := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_STANDALONE_URL")); url != "" {
		return Asset{PyMinor: abi, Triplet: triplet, Tag: tag, Filename: filepath.Base(url), URL: url}, nil
	}
	if p := localManifestPath(); p != "" {
		if asset, err := assetFromManifestFile(p, abi, triplet); err == nil {
			return asset, nil
		}
	}
	if repoURL != "" {
		if asset, err := assetFromFlashHub(ctx, repoURL, abi, triplet); err == nil {
			return asset, nil
		}
	}
	return Asset{}, fmt.Errorf("no python-standalone asset for %s/%s (tag %s); set FLASHCLI_PYTHON_STANDALONE_URL or FLASHCLI_PYTHON_STANDALONE_MANIFEST", abi, triplet, tag)
}

func localManifestPath() string {
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_STANDALONE_MANIFEST")); v != "" {
		if _, err := os.Stat(v); err == nil {
			return v
		}
		return ""
	}
	for _, p := range []string{
		filepath.Join(paths.Home(), "python-standalone", manifestName),
		filepath.Join("dist", "python-standalone", manifestName),
	} {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

func assetFromManifestFile(path, abi, triplet string) (Asset, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return Asset{}, err
	}
	var m standaloneManifest
	if err := json.Unmarshal(blob, &m); err != nil {
		return Asset{}, err
	}
	return matchAsset(m, abi, triplet)
}

func assetFromFlashHub(ctx context.Context, repoURL, abi, triplet string) (Asset, error) {
	client := flashhub.NewClient()
	ix, err := client.FetchIndex(ctx, repoURL, true)
	if err != nil {
		return Asset{}, err
	}
	entry := ix.Find(manifestName)
	if entry == nil {
		return Asset{}, fmt.Errorf("no %s in FlashHub repo %q", manifestName, repoURL)
	}
	dest := filepath.Join(paths.Cache(), "python-standalone", "manifest.json")
	if err := client.DownloadFile(ctx, *entry, dest, false, true); err != nil {
		return Asset{}, err
	}
	asset, err := assetFromManifestFile(dest, abi, triplet)
	if err != nil {
		return Asset{}, err
	}
	// Enrich URL from the repo index (CDN) when the manifest points elsewhere.
	for _, f := range ix.Files {
		if filepath.Base(f.Path) == asset.Filename {
			asset.URL = f.URL
			if asset.MD5 == "" {
				asset.MD5 = f.MD5
			}
			break
		}
	}
	return asset, nil
}

func matchAsset(m standaloneManifest, abi, triplet string) (Asset, error) {
	for _, f := range m.Files {
		if f.PyMinor == abi && f.Triplet == triplet {
			name := f.Filename
			if name == "" {
				name = filepath.Base(f.Path)
			}
			return Asset{PyMinor: abi, Triplet: triplet, Tag: f.Tag, Filename: name, URL: f.URL, MD5: f.MD5}, nil
		}
	}
	return Asset{}, fmt.Errorf("no %s/%s entry in manifest", abi, triplet)
}

// InstallStandalone downloads and extracts standalone Python under Root().
func InstallStandalone(ctx context.Context, abi string, quiet bool) (string, error) {
	root := Root()
	mmStr := mm(abi)
	dest := filepath.Join(root, mmStr)
	if bin, ok := installedBin(dest, abi); ok {
		return bin, nil
	}
	triplet, err := Triplet()
	if err != nil {
		return "", err
	}
	tag := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_STANDALONE_TAG"))
	if tag == "" {
		tag = DefaultStandaloneTag
	}
	asset, err := ResolveAsset(ctx, abi, triplet, tag, standaloneRepoURL())
	if err != nil {
		return "", err
	}

	cacheDir := filepath.Join(root, ".cache")
	if err := os.MkdirAll(cacheDir, 0o755); err != nil {
		return "", err
	}
	tarball := filepath.Join(cacheDir, fmt.Sprintf("cpython-%s-%s.tar.gz", mmStr, tag))
	if err := downloadFile(ctx, asset.URL, tarball, asset.MD5); err != nil {
		return "", err
	}
	if err := os.RemoveAll(dest); err != nil {
		return "", err
	}
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return "", err
	}
	if err := extractPython(tarball, dest); err != nil {
		return "", err
	}
	bin, ok := installedBin(dest, abi)
	if !ok {
		return "", fmt.Errorf("standalone extract failed under %s/bin", dest)
	}
	link := filepath.Join(dest, "bin", "python"+mmStr)
	if _, err := os.Lstat(link); err != nil {
		_ = os.Symlink(filepath.Base(bin), link)
	}
	RegisterPythonBin(abi, bin)
	return bin, nil
}

func installedBin(dest, abi string) (string, bool) {
	binDir := filepath.Join(dest, "bin")
	for _, name := range []string{"python" + mm(abi), "python3", "python"} {
		candidate := filepath.Join(binDir, name)
		if isExecutable(candidate) && reportsMinor(candidate, abi) {
			abs, err := filepath.Abs(candidate)
			if err == nil {
				return abs, true
			}
			return candidate, true
		}
	}
	return "", false
}

// RegisterPythonBin sets and persists FLASHCLI_PY<abi>_BIN.
func RegisterPythonBin(abi, bin string) {
	varName := "FLASHCLI_PY" + abi + "_BIN"
	_ = os.Setenv(varName, bin)
	path := EnvFile()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	var lines []string
	if blob, err := os.ReadFile(path); err == nil {
		for _, ln := range strings.Split(string(blob), "\n") {
			if strings.HasPrefix(strings.TrimSpace(ln), "export "+varName+"=") {
				continue
			}
			if strings.TrimSpace(ln) != "" {
				lines = append(lines, ln)
			}
		}
	}
	lines = append(lines, fmt.Sprintf("export %s=%s", varName, bin))
	_ = os.WriteFile(path, []byte("# Generated by flashcli — bundle runtime Python interpreters\n"+strings.Join(lines, "\n")+"\n"), 0o644)
}

func downloadFile(ctx context.Context, url, dest, wantMD5 string) error {
	if url == "" {
		return fmt.Errorf("empty python-standalone URL")
	}
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
	tmp := dest + ".part"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, resp.Body); err != nil {
		out.Close()
		_ = os.Remove(tmp)
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	if wantMD5 != "" {
		got, err := fileMD5(tmp)
		if err != nil || !strings.EqualFold(got, wantMD5) {
			_ = os.Remove(tmp)
			return fmt.Errorf("MD5 mismatch for %s: expected %s, got %s", url, wantMD5, got)
		}
	}
	return os.Rename(tmp, dest)
}

func extractPython(tarball, dest string) error {
	f, err := os.Open(tarball)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		name := strings.TrimPrefix(hdr.Name, "./")
		if name != "python" && !strings.HasPrefix(name, "python/") {
			continue
		}
		rel := strings.TrimPrefix(name, "python")
		rel = strings.TrimPrefix(rel, "/")
		if rel == "" {
			continue
		}
		target := filepath.Join(dest, filepath.FromSlash(rel))
		if !strings.HasPrefix(target, filepath.Clean(dest)+string(os.PathSeparator)) {
			return fmt.Errorf("unsafe path in tarball: %s", hdr.Name)
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)|0o700); err != nil {
				return err
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			if err := writeFileFromTar(target, tr, os.FileMode(hdr.Mode)); err != nil {
				return err
			}
		case tar.TypeSymlink:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			_ = os.Remove(target)
			if err := os.Symlink(hdr.Linkname, target); err != nil {
				return err
			}
		case tar.TypeLink:
			linkRel := strings.TrimPrefix(strings.TrimPrefix(hdr.Linkname, "python"), "/")
			src := filepath.Join(dest, filepath.FromSlash(linkRel))
			if err := os.Link(src, target); err != nil {
				// Fall back to copy when hardlink source ordering/paths differ.
				_ = copyFile(src, target)
			}
		}
	}
	return nil
}

func writeFileFromTar(target string, r io.Reader, mode os.FileMode) error {
	out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode|0o600)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, r); err != nil {
		out.Close()
		return err
	}
	return out.Close()
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
	_, err = io.Copy(out, in)
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

func standaloneRepoURL() string {
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON_REPO")); v != "" {
		return strings.TrimRight(v, "/")
	}
	base := flashhub.APIBase()
	return strings.TrimRight(base, "/") + "/flashcli-bundle/python-standalone:1.0.0"
}

func expandHome(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(p, "~/"))
		}
	}
	return p
}
