// Package venv creates and reuses the per-bundle Python virtualenv.
//
// Mirrors the essential behaviour of src/flashcli/runtime/bundle_venv.py:
// a venv keyed by manifest python_abi + torch index + python_dependencies,
// with a fingerprint file to avoid rebuilding.
package venv

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	stdruntime "runtime"
	"strconv"
	"strings"
	"sync"
	"time"

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

// streamRunner runs commands and forwards their output lines to the context
// progress sink. On Linux it runs interactive installers through `script` so
// uv emits its download progress bars (it disables them when stderr is a pipe).
type streamRunner struct{ stdio bool }

func (r streamRunner) Run(ctx context.Context, argv []string, env []string) error {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Env = env
	if progress.SinkFromContext(ctx) != nil && stdruntime.GOOS == "linux" {
		if script, err := exec.LookPath("script"); err == nil {
			cmd = exec.CommandContext(ctx, script, "-qefc", shellJoin(argv), "/dev/null")
			cmd.Env = append(append([]string{}, env...), "TERM=xterm-256color")
		}
	}
	out := &lineWriter{ctx: ctx}
	errOut := &lineWriter{ctx: ctx}
	if r.stdio {
		out.out = os.Stdout
		errOut.out = os.Stderr
	}
	cmd.Stdout = out
	cmd.Stderr = errOut
	err := cmd.Run()
	out.Flush()
	errOut.Flush()
	if err != nil {
		return fmt.Errorf("%s: %w", strings.Join(argv, " "), err)
	}
	return nil
}

func shellJoin(argv []string) string {
	parts := make([]string, len(argv))
	for i, a := range argv {
		parts[i] = "'" + strings.ReplaceAll(a, "'", `'\''`) + "'"
	}
	return strings.Join(parts, " ")
}

var (
	ansiRe     = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)
	byteFracRe = regexp.MustCompile(`([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]i?B)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]i?B)`)
)

func cleanLine(s string) string {
	s = ansiRe.ReplaceAllString(s, "")
	s = strings.ReplaceAll(s, "\x1b", "")
	s = strings.TrimLeftFunc(s, func(r rune) bool {
		return r == '▸' || r == '•' || (r >= 0x2800 && r <= 0x28FF)
	})
	fields := strings.Fields(s)
	out := fields[:0]
	for _, f := range fields {
		if isProgressBar(f) {
			continue
		}
		out = append(out, f)
	}
	return strings.Join(out, " ")
}

func isProgressBar(s string) bool {
	if len(s) < 2 {
		return false
	}
	for _, r := range s {
		switch r {
		case '-', '=', '#', '█', '░', '▰', '▱', '▌', '▐':
		default:
			return false
		}
	}
	return true
}

func withPercent(s string) string {
	if strings.Contains(s, "%") {
		return s
	}
	m := byteFracRe.FindStringSubmatch(s)
	if m == nil {
		return s
	}
	done, total := byteValue(m[1], m[2]), byteValue(m[3], m[4])
	if total <= 0 {
		return s
	}
	pct := int(done*100/total + 0.5)
	if pct > 100 {
		pct = 100
	}
	return fmt.Sprintf("%s  %d%%", s, pct)
}

func byteValue(num, unit string) float64 {
	v, err := strconv.ParseFloat(num, 64)
	if err != nil {
		return 0
	}
	switch strings.ToUpper(strings.TrimSpace(unit)) {
	case "KB":
		v *= 1000
	case "MB":
		v *= 1000 * 1000
	case "GB":
		v *= 1000 * 1000 * 1000
	case "KIB":
		v *= 1024
	case "MIB":
		v *= 1024 * 1024
	case "GIB":
		v *= 1024 * 1024 * 1024
	case "TIB":
		v *= 1024 * 1024 * 1024 * 1024
	}
	return v
}

// lineWriter forwards complete output lines to the progress sink. Progress
// bars are throttled so a fast terminal refresh does not flood the job log.
type lineWriter struct {
	ctx context.Context
	out io.Writer
	mu  sync.Mutex
	buf []byte

	lastEmit time.Time
	pending  string
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexAny(w.buf, "\r\n")
		if i < 0 {
			break
		}
		raw := string(w.buf[:i])
		w.buf = w.buf[i+1:]
		w.handleLine(raw)
	}
	if len(w.buf) > 4096 {
		w.handleLine(string(w.buf))
		w.buf = nil
	}
	return len(p), nil
}

func (w *lineWriter) handleLine(raw string) {
	line := withPercent(cleanLine(raw))
	if line == "" {
		return
	}
	force := false
	for _, marker := range []string{"Downloaded", "Installed", "Resolved", "Building", "Built", "Using Python"} {
		if strings.Contains(line, marker) {
			force = true
			break
		}
	}
	now := time.Now()
	if !force && now.Sub(w.lastEmit) < 250*time.Millisecond {
		w.pending = line
		return
	}
	w.lastEmit = now
	w.pending = ""
	if w.out != nil {
		fmt.Fprintln(w.out, line)
	}
	progress.EmitCtx(w.ctx, "%s", line)
}

func (w *lineWriter) Flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	line := withPercent(cleanLine(string(w.buf)))
	w.buf = nil
	if line == "" {
		line = w.pending
	}
	w.pending = ""
	if line == "" {
		return
	}
	if w.out != nil {
		fmt.Fprintln(w.out, line)
	}
	progress.EmitCtx(w.ctx, "%s", line)
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
		opt.Runner = streamRunner{stdio: !opt.Quiet}
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
			// A matching fingerprint is not enough: a venv built by an older
			// host (or with a mismatched FLASHCLI_BASE_PYTHON) must be rebuilt
			// when its interpreter does not match the manifest python_abi.
			if blob, err := os.ReadFile(fpPath); err == nil && strings.TrimSpace(string(blob)) == fp && pythonMatches(existing, abi) {
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
		progress.NoteCtx(ctx, "venv: creating %s (Python 3.%s, base %s)", venv, abi[1:], basePython)
		if _, origin, oerr := FlashcliBundleSpecOrigin(); oerr == nil {
			progress.NoteCtx(ctx, "venv: flashcli-bundle[infer] from %s", origin)
		}
		if torchPkg, _ := ParseTorchDependency(m.PythonDependencies()["torch"]); torchPkg != "" {
			idx := "PyPI default index"
			if torchIndex != "" {
				idx = mirror.TorchIndexURL(torchIndex)
			}
			progress.NoteCtx(ctx, "venv: torch %s from %s", torchPkg, idx)
		}
	}
	inst, err := SelectInstaller(ctx, opt)
	if err != nil {
		return "", err
	}
	if !opt.Quiet {
		if inst.UV != "" {
			progress.NoteCtx(ctx, "venv: installer uv (%s)", inst.UV)
		} else {
			progress.NoteCtx(ctx, "venv: installer pip (FLASHCLI_VENV_BACKEND=pip)")
		}
	}
	if err := os.RemoveAll(venv); err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(venv), 0o755); err != nil {
		return "", err
	}
	if err := inst.CreateVenv(ctx, basePython, venv); err != nil {
		return "", err
	}
	python, err := runtime.VenvPython(runtimeID)
	if err != nil {
		return "", fmt.Errorf("venv created but no interpreter under %s", venv)
	}
	if want := abi[0:1] + "." + abi[1:]; !pythonMatches(python, abi) {
		return "", fmt.Errorf("%w: venv interpreter %s is not Python %s (python_abi=%s); set FLASHCLI_BASE_PYTHON/FLASHCLI_PY%s_BIN or remove %s",
			errs.Environment, python, want, abi, abi, venv)
	}
	if inst.UV == "" {
		_ = inst.Runner.Run(ctx, []string{python, "-m", "pip", "install", "-q", "--upgrade", "pip"}, inst.env())
	}
	for _, args := range installSpecs(m, torchIndex, opt.Quiet) {
		if err := inst.Install(ctx, python, args); err != nil {
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

// installSpecs returns backend-neutral pip-style argument lists (no
// interpreter prefix): each begins with -q when quiet, then index/package args.
func installSpecs(m *manifest.Manifest, torchIndex string, quiet bool) [][]string {
	base := func(extra ...string) []string {
		args := []string{}
		if quiet {
			args = append(args, "-q")
		}
		return append(args, extra...)
	}
	var plan [][]string
	spec, err := FlashcliBundleSpec()
	if err != nil {
		spec = "flashcli-bundle[infer]"
	}
	plan = append(plan, base(append(mirror.PipExtraArgs(), spec)...))

	torchPkg, _ := ParseTorchDependency(m.PythonDependencies()["torch"])
	if torchPkg != "" {
		args := base()
		if torchIndex != "" {
			args = append(args, "--index-url", mirror.TorchIndexURL(torchIndex))
		}
		args = append(args, torchPkg)
		plan = append(plan, args)
	}
	if deps := pipDependencies(m); len(deps) > 0 {
		plan = append(plan, base(append(mirror.PipExtraArgs(), deps...)...))
	}
	return plan
}

// InstallPlan returns the pip install commands for the bundle venv (pip
// backend). uv uses installSpecs via Installer.Install.
func InstallPlan(python string, m *manifest.Manifest, torchIndex string, quiet bool) [][]string {
	var out [][]string
	for _, args := range installSpecs(m, torchIndex, quiet) {
		out = append(out, append([]string{python, "-m", "pip", "install"}, args...))
	}
	return out
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

// pythonMatches reports whether pyBin is CPython <abi> (e.g. "310" -> 3.10).
func pythonMatches(pyBin, abi string) bool {
	out, err := exec.Command(pyBin, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')").Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == abi[0:1]+"."+abi[1:]
}

// ResolveBasePython resolves a host interpreter for the bundle python_abi.
// Every candidate is version-checked: a generic python3 (e.g. 3.12) must never
// silently build a venv for a bundle that declared python_abi=310.
func ResolveBasePython(abi string) (string, error) {
	pythonprovision.LoadEnvFile()
	want := abi[0:1] + "." + abi[1:]
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_PY" + abi + "_BIN")); v != "" {
		if pythonMatches(v, abi) {
			return v, nil
		}
		return "", fmt.Errorf("FLASHCLI_PY%s_BIN=%s is not Python %s (python_abi=%s)", abi, v, want, abi)
	}
	if p, ok := pythonprovision.Resolve(abi); ok && pythonMatches(p, abi) {
		return p, nil
	}
	if v := strings.TrimSpace(os.Getenv("FLASHCLI_BASE_PYTHON")); v != "" {
		if pythonMatches(v, abi) {
			return v, nil
		}
		return "", fmt.Errorf("FLASHCLI_BASE_PYTHON=%s is not Python %s (python_abi=%s)", v, want, abi)
	}
	for _, name := range []string{"python" + want, "python" + abi[1:], "python3"} {
		if path, err := exec.LookPath(name); err == nil && pythonMatches(path, abi) {
			return path, nil
		}
	}
	return "", fmt.Errorf("no Python %s interpreter found for python_abi=%s "+
		"(set FLASHCLI_PY%s_BIN or FLASHCLI_BASE_PYTHON)", want, abi, abi)
}
