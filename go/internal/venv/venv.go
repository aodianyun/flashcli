// Package venv creates and reuses the per-bundle Python virtualenv.
//
// Mirrors the essential behaviour of src/flashcli/runtime/bundle_venv.py:
// a venv keyed by manifest python_abi + torch index + python_dependencies,
// with a fingerprint file to avoid rebuilding.
package venv

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/mirror"
	"github.com/aodianyun/flashcli/go/internal/progress"
	"github.com/aodianyun/flashcli/go/internal/pythonprovision"
	"github.com/aodianyun/flashcli/go/internal/runtime"
)

// Runner executes external commands; injectable for tests.
type Runner interface {
	Run(ctx context.Context, argv []string, env []string) error
}

// ExecRunner runs commands via os/exec.
type ExecRunner struct{ Stdio bool }

// Run implements Runner.
func (e ExecRunner) Run(ctx context.Context, argv []string, env []string) error {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = env
	if e.Stdio {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("%s: %w", strings.Join(argv, " "), err)
	}
	return nil
}

// Options controls Ensure.
type Options struct {
	Force         bool
	Quiet         bool
	BasePython    string
	Runner        Runner
	SkipSetup     bool
	NoAutoInstall bool
}

// Fingerprint mirrors _manifest_fingerprint.
func Fingerprint(m *manifest.Manifest, torchIndex string) string {
	payload := map[string]any{
		"python_abi":  m.Raw["python_abi"],
		"torch_index": torchIndex,
		"deps":        m.Raw["python_dependencies"],
	}
	blob, _ := json.Marshal(payload)
	sum := sha256.Sum256(blob)
	return hex.EncodeToString(sum[:])
}

// Ensure creates or reuses the bundle venv and returns its interpreter path.
func Ensure(ctx context.Context, runtimeID string, m *manifest.Manifest, opt Options) (string, error) {
	if opt.SkipSetup {
		return runtime.VenvPython(runtimeID)
	}
	if opt.Runner == nil {
		opt.Runner = ExecRunner{Stdio: !opt.Quiet}
	}
	abi, err := m.PythonABI()
	if err != nil {
		return "", err
	}
	torchIndex := TorchIndex(m)
	fp := Fingerprint(m, torchIndex)
	venv := runtime.VenvDir(runtimeID)
	fpPath := runtime.FingerprintPath(runtimeID)

	if !opt.Force {
		if existing, err := runtime.VenvPython(runtimeID); err == nil {
			if blob, err := os.ReadFile(fpPath); err == nil && strings.TrimSpace(string(blob)) == fp {
				return existing, nil
			}
		}
	}

	basePython := opt.BasePython
	if basePython == "" {
		if resolved, rerr := ResolveBasePython(abi); rerr == nil {
			basePython = resolved
		} else {
			installed, ok, ierr := pythonprovision.Ensure(ctx, abi, !opt.NoAutoInstall, opt.Quiet)
			if ierr != nil {
				return "", fmt.Errorf("%w: %s", errs.Environment, ierr)
			}
			if !ok {
				return "", fmt.Errorf("%w: %s", errs.Environment, rerr)
			}
			basePython = installed
		}
	}
	if !opt.Quiet {
		progress.Note("venv: creating %s (Python 3.%s, base %s)", venv, abi[1:], basePython)
		if _, origin, oerr := FlashcliBundleSpecOrigin(); oerr == nil {
			progress.Note("venv: flashcli-bundle[infer] from %s", origin)
		}
		if torchPkg, _ := ParseTorchDependency(m.PythonDependencies()["torch"]); torchPkg != "" {
			idx := "PyPI default index"
			if torchIndex != "" {
				idx = mirror.TorchIndexURL(torchIndex)
			}
			progress.Note("venv: torch %s from %s", torchPkg, idx)
		}
	}
	if err := os.RemoveAll(venv); err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(venv), 0o755); err != nil {
		return "", err
	}
	env := os.Environ()
	if err := opt.Runner.Run(ctx, []string{basePython, "-m", "venv", venv}, env); err != nil {
		return "", err
	}
	python, err := runtime.VenvPython(runtimeID)
	if err != nil {
		return "", fmt.Errorf("venv created but no interpreter under %s", venv)
	}
	_ = opt.Runner.Run(ctx, []string{python, "-m", "pip", "install", "-q", "--upgrade", "pip"}, env)
	for _, argv := range InstallPlan(python, m, torchIndex, opt.Quiet) {
		if err := opt.Runner.Run(ctx, argv, env); err != nil {
			return "", err
		}
	}
	if err := os.MkdirAll(runtime.Dir(runtimeID), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(fpPath, []byte(fp+"\n"), 0o644); err != nil {
		return "", err
	}
	return python, nil
}

// InstallPlan returns the pip install commands for the bundle venv. When quiet,
// `pip -q` is used (progress hidden); otherwise pip shows its own progress.
func InstallPlan(python string, m *manifest.Manifest, torchIndex string, quiet bool) [][]string {
	pip := func(extra ...string) []string {
		argv := []string{python, "-m", "pip", "install"}
		if quiet {
			argv = append(argv, "-q")
		}
		return append(argv, extra...)
	}
	var plan [][]string
	spec, err := FlashcliBundleSpec()
	if err != nil {
		spec = "flashcli-bundle[infer]"
	}
	plan = append(plan, pip(append(mirror.PipExtraArgs(), spec)...))

	torchPkg, _ := ParseTorchDependency(m.PythonDependencies()["torch"])
	if torchPkg != "" {
		argv := pip()
		if torchIndex != "" {
			argv = append(argv, "--index-url", mirror.TorchIndexURL(torchIndex))
		}
		argv = append(argv, torchPkg)
		plan = append(plan, argv)
	}
	if deps := pipDependencies(m); len(deps) > 0 {
		plan = append(plan, pip(append(mirror.PipExtraArgs(), deps...)...))
	}
	return plan
}

func pipDependencies(m *manifest.Manifest) []string {
	py := m.PythonDependencies()
	raw, ok := py["pip"].([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		if s, ok := item.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	return out
}

// ParseTorchDependency mirrors parse_torch_dependency: (spec, index).
func ParseTorchDependency(value any) (string, string) {
	switch v := value.(type) {
	case nil:
		return "", ""
	case bool:
		if !v {
			return "", ""
		}
		return "torch", ""
	case map[string]any:
		pkg := strings.TrimSpace(fmt.Sprintf("%v", v["package"]))
		if pkg == "" || pkg == "<nil>" {
			pkg = "torch"
		}
		idx := strings.TrimSpace(fmt.Sprintf("%v", v["index"]))
		if idx == "<nil>" {
			idx = ""
		}
		return pkg, idx
	case string:
		s := strings.TrimSpace(v)
		switch strings.ToLower(s) {
		case "", "skip", "none", "false":
			return "", ""
		}
		return s, ""
	}
	return "torch", ""
}

var cudaTagRe = regexp.MustCompile(`release\s+([0-9]+)\.([0-9]+)`)

// TorchIndex mirrors bundle_torch_index (explicit index, else detected tag).
func TorchIndex(m *manifest.Manifest) string {
	_, idx := ParseTorchDependency(m.PythonDependencies()["torch"])
	if idx != "" && !strings.EqualFold(idx, "auto") {
		return idx
	}
	if override := strings.TrimSpace(os.Getenv("FLASHCLI_TORCH_INDEX")); override != "" {
		return override
	}
	return torchIndexForTag(detectCudaTag())
}

func torchIndexForTag(tag string) string {
	if tag == "128" || tag == "130" {
		return "cu128"
	}
	return "cu124"
}

func detectCudaTag() string {
	if tag := strings.TrimSpace(os.Getenv("FLASHCLI_CUDA_TAG")); tag != "" {
		return tag
	}
	out, err := exec.Command("nvcc", "--version").Output()
	if err == nil {
		if mm := cudaTagRe.FindStringSubmatch(string(out)); mm != nil {
			ver := mm[1] + "." + mm[2]
			switch {
			case ver >= "12.8":
				return "128"
			case ver >= "12.4":
				return "124"
			}
		}
	}
	return "124"
}

// ResolveBasePython resolves a host interpreter for the bundle python_abi.
func ResolveBasePython(abi string) (string, error) {
	pythonprovision.LoadEnvFile()
	if p, ok := pythonprovision.Resolve(abi); ok {
		return p, nil
	}
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_BASE_PYTHON")); v != "" {
		return v, nil
	}
	major, minor := string(abi[0]), abi[1:]
	for _, name := range []string{"python" + major + "." + minor, "python" + minor, "python3"} {
		if path, err := exec.LookPath(name); err == nil {
			return path, nil
		}
	}
	return "", fmt.Errorf("no Python 3.%s interpreter found for python_abi=%s "+
		"(set FLASHCLI_PY%s_BIN or FLASHCLI_BASE_PYTHON)", minor, abi, abi)
}
