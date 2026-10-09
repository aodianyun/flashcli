package venv

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

// LoadInstallEnv applies ~/.flashcli/install.env (written by the installer),
// without overriding already-set env vars.
func LoadInstallEnv() {
	blob, err := os.ReadFile(filepath.Join(paths.Home(), "install.env"))
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
		if key != "" && val != "" {
			if _, exists := os.LookupEnv(key); !exists {
				_ = os.Setenv(key, val)
			}
		}
	}
}

// FlashcliBundleSpec resolves the pip spec for installing flashcli-bundle into a
// bundle venv (no PyPI publication). Mirrors flashcli_bundle.infer.deps.
//
// Order: FLASHCLI_BUNDLE_PIP_SPEC → local repo checkout → FLASHCLI_INSTALL_REPO/REF
// (git) → default GitHub repo.
func FlashcliBundleSpec() (string, error) {
	spec, _, err := FlashcliBundleSpecOrigin()
	return spec, err
}

// FlashcliBundleSpecOrigin returns the pip spec plus a human-readable origin
// describing where it will be installed from (for status output).
func FlashcliBundleSpecOrigin() (spec, origin string, err error) {
	LoadInstallEnv()
	if s := strings.TrimSpace(os.Getenv("FLASHCLI_BUNDLE_PIP_SPEC")); s != "" {
		return s, "FLASHCLI_BUNDLE_PIP_SPEC=" + s, nil
	}
	if root, ok := localBundleRepo(); ok {
		dir := filepath.Join(root, "flashcli-bundle")
		return dir + "[infer]", "local checkout " + dir, nil
	}
	repo := strings.TrimSpace(os.Getenv("FLASHCLI_INSTALL_REPO"))
	if repo == "" {
		repo = "https://github.com/aodianyun/flashcli.git"
	}
	ref := strings.TrimSpace(os.Getenv("FLASHCLI_INSTALL_REF"))
	if ref == "" {
		ref = "main"
	}
	s := fmt.Sprintf("flashcli-bundle[infer] @ git+%s@%s#subdirectory=flashcli-bundle", repo, ref)
	return s, fmt.Sprintf("git+%s@%s", repo, ref), nil
}

func localBundleRepo() (string, bool) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", false
	}
	for dir := cwd; ; {
		if hasPyproject(filepath.Join(dir, "flashcli-bundle")) {
			return dir, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", false
}

func hasPyproject(dir string) bool {
	blob, err := os.ReadFile(filepath.Join(dir, "pyproject.toml"))
	if err != nil {
		return false
	}
	return strings.Contains(string(blob), `name = "flashcli-bundle"`)
}
