// Package cuda ensures the bundle venv provides the CUDA userland libraries
// (libcublas/libcudart) required by native .so tagged cu124/cu128/cu130.
// Mirrors flashcli_bundle/cuda_userland.py.
package cuda

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"github.com/ebitengine/purego"

	"github.com/aodianyun/flashcli/go/internal/errs"
)

var sonamesByFamily = map[string][]string{
	"12": {"libcublas.so.12", "libcudart.so.12"},
	"13": {"libcublas.so.13", "libcudart.so.13"},
}

var pipPackagesByFamily = map[string][]string{
	"12": {"nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12"},
	"13": {"nvidia-cublas>=13,<14", "nvidia-cuda-runtime>=13,<14"},
}

// Family groups a cuda tag (e.g. "130" -> "13").
func Family(tag string) string {
	tag = strings.TrimSpace(tag)
	switch {
	case strings.HasPrefix(tag, "13") || tag == "130":
		return "13"
	case strings.HasPrefix(tag, "12") || tag == "124" || tag == "128" || tag == "120":
		return "12"
	}
	if len(tag) >= 2 {
		return tag[:2]
	}
	return tag
}

// SonamesForTag returns the required SONAMEs for a cuda tag.
func SonamesForTag(tag string) []string { return sonamesByFamily[Family(tag)] }

// PipPackagesForTag returns the pip packages providing the SONAMEs.
func PipPackagesForTag(tag string) []string { return pipPackagesByFamily[Family(tag)] }

// Purelib returns the venv site-packages dir containing `python`.
func Purelib(python string) string {
	venvRoot := filepath.Dir(filepath.Dir(python))
	matches, _ := filepath.Glob(filepath.Join(venvRoot, "lib", "python*", "site-packages"))
	sort.Strings(matches)
	if len(matches) > 0 {
		return matches[len(matches)-1]
	}
	return ""
}

// NvidiaLibDirs returns venv nvidia lib dirs (cu13/cu12 + legacy layouts).
func NvidiaLibDirs(purelib string) []string {
	if purelib == "" {
		return nil
	}
	root := filepath.Join(purelib, "nvidia")
	if info, err := os.Stat(root); err != nil || !info.IsDir() {
		return nil
	}
	seen := map[string]bool{}
	var dirs []string
	add := func(d string) {
		if d == "" || seen[d] {
			return
		}
		if info, err := os.Stat(d); err == nil && info.IsDir() {
			seen[d] = true
			dirs = append(dirs, d)
		}
	}
	for _, name := range []string{"cu13", "cu12"} {
		add(filepath.Join(root, name, "lib"))
	}
	entries, _ := os.ReadDir(root)
	for _, e := range entries {
		if e.IsDir() {
			add(filepath.Join(root, e.Name(), "lib"))
			add(filepath.Join(root, e.Name(), "lib64"))
		}
	}
	return dirs
}

// FindSoname locates a SONAME under the venv nvidia tree.
func FindSoname(purelib, soname string) string {
	root := filepath.Join(purelib, "nvidia")
	for _, d := range NvidiaLibDirs(purelib) {
		candidate := filepath.Join(d, soname)
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	var found string
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || d.Name() != soname || found != "" {
			return nil
		}
		found = path
		return fs.SkipAll
	})
	return found
}

func loadable(path string) bool {
	handle, err := purego.Dlopen(path, purego.RTLD_NOW)
	if err != nil {
		return false
	}
	_ = purego.Dlclose(handle)
	return true
}

func loadableBare(soname string) bool {
	handle, err := purego.Dlopen(soname, purego.RTLD_NOW)
	if err != nil {
		return false
	}
	_ = purego.Dlclose(handle)
	return true
}

// PrependLDLibraryPath prepends dirs (deduped) to LD_LIBRARY_PATH; returns added.
func PrependLDLibraryPath(dirs []string) []string {
	if len(dirs) == 0 {
		return nil
	}
	var existing []string
	seen := map[string]bool{}
	for _, p := range strings.Split(os.Getenv("LD_LIBRARY_PATH"), ":") {
		if p = strings.TrimSpace(p); p != "" && !seen[p] {
			seen[p] = true
			existing = append(existing, p)
		}
	}
	var added []string
	for i := len(dirs) - 1; i >= 0; i-- {
		if !seen[dirs[i]] {
			existing = append([]string{dirs[i]}, existing...)
			seen[dirs[i]] = true
			added = append(added, dirs[i])
		}
	}
	_ = os.Setenv("LD_LIBRARY_PATH", strings.Join(existing, ":"))
	return added
}

// Runner runs pip; injectable for tests.
type Runner interface {
	Run(ctx context.Context, argv []string) error
}

// ExecRunner runs commands via os/exec.
type ExecRunner struct{}

func (ExecRunner) Run(ctx context.Context, argv []string) error {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = os.Environ()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s: %w", strings.Join(argv, " "), err)
	}
	return nil
}

// Ensure makes the required CUDA libs loadable (installing into the venv if allowed).
func Ensure(ctx context.Context, python, cudaTag string, quiet, install bool, runner Runner) error {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("FLASHCLI_SKIP_CUDA_USERLAND"))) {
	case "1", "true", "yes", "on":
		return nil
	}
	sonames := SonamesForTag(cudaTag)
	if len(sonames) == 0 {
		return nil
	}
	if runner == nil {
		runner = ExecRunner{}
	}
	purelib := Purelib(python)
	PrependLDLibraryPath(NvidiaLibDirs(purelib))

	missing := func() []string {
		var out []string
		for _, name := range sonames {
			if path := FindSoname(purelib, name); path != "" && loadable(path) {
				continue
			}
			// System loader fallback (ld.so.cache / LD_LIBRARY_PATH): a host CUDA
			// toolkit providing the SONAME means no pip install is needed.
			if loadableBare(name) {
				continue
			}
			out = append(out, name)
		}
		return out
	}

	if len(missing()) == 0 {
		return nil
	}
	packages := PipPackagesForTag(cudaTag)
	if !install || len(packages) == 0 {
		return errs.EnvWrapf("Missing CUDA userland libraries for native cu%s: %s (venv %s)", cudaTag, strings.Join(missing(), ", "), python)
	}
	argv := append([]string{python, "-m", "pip", "install"}, packages...)
	if quiet {
		argv = append(argv, "-q")
	}
	if err := runner.Run(ctx, argv); err != nil {
		return errs.EnvWrapf("pip install failed for CUDA userland cu%s: %s", cudaTag, err)
	}
	PrependLDLibraryPath(NvidiaLibDirs(purelib))
	if still := missing(); len(still) > 0 {
		return errs.EnvWrapf("Missing CUDA userland libraries for native cu%s after install: %s", cudaTag, strings.Join(still, ", "))
	}
	return nil
}
