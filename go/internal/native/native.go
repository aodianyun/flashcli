// Package native parses and validates FlashRT native “.so“ artifact names
// under runtime/<env-key>/ (docs/bundle_publish_standard.md section 5).
// Mirrors flashcli_bundle/native_naming.py + native_validate.py (filename checks).
package native

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/preflight"
)

var knownOS = map[string]bool{"linux": true, "darwin": true, "win32": true, "windows": true}
var knownArch = map[string]bool{"x86_64": true, "aarch64": true, "arm64": true}

var flashrtABIRe = regexp.MustCompile(`(?i)^(?:dev|v?\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9._+-]*)?|[a-f0-9]{7,})$`)

// Parsed is a parsed native artifact name.
type Parsed struct {
	ModuleBase  string
	FlashrtABI  string
	EnvKey      string
	PythonMinor string
}

// CatalogKey is the env key used as the artifact's target cell.
func (p Parsed) CatalogKey() string { return p.EnvKey }

func splitNonEmpty(s, sep string) []string {
	var out []string
	for _, p := range strings.Split(s, sep) {
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// inferEnvKeyFromStem extracts the env key suffix from a tagged stem.
func inferEnvKeyFromStem(stem string) string {
	parts := splitNonEmpty(stem, "-")
	if len(parts) < 4 {
		return ""
	}
	starts := []int{1, 2}
	if len(parts) >= 7 {
		starts = []int{2, 1}
	}
	for _, start := range starts {
		if len(parts) <= start {
			continue
		}
		candidate := strings.Join(parts[start:], "-")
		if env, err := preflight.ParseEnvKey(candidate); err == nil && knownOS[env.OSName] && knownArch[env.Arch] {
			return candidate
		}
	}
	for i := len(parts) - 3; i > 0; i-- {
		candidate := strings.Join(parts[i:], "-")
		if env, err := preflight.ParseEnvKey(candidate); err == nil && knownOS[env.OSName] && knownArch[env.Arch] {
			return candidate
		}
	}
	return ""
}

func splitModuleBaseAndABI(moduleAndABI string) (string, string, bool) {
	if !strings.HasPrefix(moduleAndABI, "flash_rt") {
		return "", "", false
	}
	if !strings.Contains(moduleAndABI, "-") {
		return moduleAndABI, "dev", true
	}
	idx := strings.LastIndex(moduleAndABI, "-")
	moduleBase := moduleAndABI[:idx]
	abi := moduleAndABI[idx+1:]
	if moduleBase == "" || abi == "" || !flashrtABIRe.MatchString(abi) {
		return "", "", false
	}
	return moduleBase, abi, true
}

// ParseStem parses "{module_base}-{abi}-{envKey}" or legacy "{module_base}-{envKey}".
func ParseStem(stem, envKey string) (Parsed, bool) {
	suffix := "-" + envKey
	if !strings.HasSuffix(stem, suffix) {
		return Parsed{}, false
	}
	moduleAndABI := stem[:len(stem)-len(suffix)]
	moduleBase, abi, ok := splitModuleBaseAndABI(moduleAndABI)
	if !ok {
		return Parsed{}, false
	}
	env, err := preflight.ParseEnvKey(envKey)
	if err != nil {
		return Parsed{}, false
	}
	return Parsed{ModuleBase: moduleBase, FlashrtABI: abi, EnvKey: envKey, PythonMinor: env.PythonMinor}, true
}

// ParseFilename parses a filename, inferring the env key when not supplied.
func ParseFilename(filename, envKey string) (Parsed, bool) {
	stem := strings.TrimSuffix(filepath.Base(filename), ".so")
	key := envKey
	if key == "" {
		key = inferEnvKeyFromStem(stem)
	}
	if key == "" {
		return Parsed{}, false
	}
	return ParseStem(stem, key)
}

func soFiles(dir string) []string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".so") {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

// DiscoverModuleBases returns module_base names from tagged .so in a cell dir.
func DiscoverModuleBases(dir, envKey string) []string {
	seen := map[string]bool{}
	for _, name := range soFiles(dir) {
		var parsed Parsed
		var ok bool
		if envKey != "" {
			parsed, ok = ParseStem(strings.TrimSuffix(name, ".so"), envKey)
		} else {
			parsed, ok = ParseFilename(name, "")
		}
		if ok && parsed.ModuleBase != "" {
			seen[parsed.ModuleBase] = true
		}
	}
	out := make([]string, 0, len(seen))
	for k := range seen {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// NativeSOPaths returns absolute paths of recognized tagged .so in a cell dir.
func NativeSOPaths(dir, envKey string) []string {
	var out []string
	for _, name := range soFiles(dir) {
		if _, ok := ParseFilename(name, envKey); ok {
			out = append(out, filepath.Join(dir, name))
		}
	}
	return out
}

// ValidateRuntimeMatrix checks every manifest runtime cell for recognized .so.
func ValidateRuntimeMatrix(root string, runtimeMap map[string]string) []string {
	var errors []string
	for envKey, rel := range runtimeMap {
		dir := filepath.Join(root, filepath.FromSlash(strings.Trim(rel, "/")))
		errors = append(errors, ValidateRuntimeCell(root, envKey, dir)...)
	}
	sort.Strings(errors)
	return errors
}

// ValidateRuntimeCell checks one runtime/<env-key>/ directory.
func ValidateRuntimeCell(root, envKey, nativeDir string) []string {
	rel, _ := filepath.Rel(root, nativeDir)
	rel = filepath.ToSlash(rel)
	var errors []string
	if info, err := os.Stat(nativeDir); err != nil || !info.IsDir() {
		return []string{"missing " + rel + "/ for runtime " + quote(envKey)}
	}

	matched := map[string]bool{}
	for _, name := range soFiles(nativeDir) {
		parsed, ok := ParseFilename(name, envKey)
		if !ok {
			if inferred, ok2 := ParseFilename(name, ""); ok2 && inferred.CatalogKey() != envKey {
				errors = append(errors, rel+"/"+name+": filename tag "+quote(inferred.CatalogKey())+" does not match runtime cell "+quote(envKey))
			} else {
				errors = append(errors, rel+"/"+name+": unrecognized native artifact filename (expected *-*-"+envKey+".so)")
			}
			continue
		}
		if parsed.CatalogKey() != envKey {
			errors = append(errors, rel+"/"+name+": filename tag "+quote(parsed.CatalogKey())+" does not match runtime cell "+quote(envKey))
			continue
		}
		matched[parsed.ModuleBase] = true
	}
	if len(matched) == 0 {
		return append(errors, rel+"/ has no recognized native .so artifacts (expected tagged files such as *-*-"+envKey+".so)")
	}

	modules := make([]string, 0, len(matched))
	for m := range matched {
		modules = append(modules, m)
	}
	sort.Strings(modules)

	var refs []Parsed
	for _, mod := range modules {
		found := false
		for _, name := range soFiles(nativeDir) {
			parsed, ok := ParseFilename(name, envKey)
			if ok && parsed.ModuleBase == mod && parsed.CatalogKey() == envKey {
				refs = append(refs, parsed)
				found = true
				break
			}
		}
		if !found {
			errors = append(errors, "missing "+rel+"/"+mod+"-*-"+envKey+".so")
		}
	}
	if len(refs) >= 2 {
		ref := refs[0]
		for _, tag := range refs[1:] {
			if tag.PythonMinor != ref.PythonMinor {
				errors = append(errors, envKey+": inconsistent python_abi — "+ref.ModuleBase+" -py"+ref.PythonMinor+" vs "+tag.ModuleBase+" -py"+tag.PythonMinor)
			}
			if tag.EnvKey != ref.EnvKey {
				errors = append(errors, envKey+": inconsistent env key between "+ref.ModuleBase+" and "+tag.ModuleBase)
			}
			if tag.FlashrtABI != ref.FlashrtABI {
				errors = append(errors, envKey+": inconsistent FlashRT ABI segment ("+ref.ModuleBase+" "+quote(tag.FlashrtABI)+" vs "+tag.ModuleBase+" "+quote(tag.FlashrtABI)+")")
			}
		}
	}
	return errors
}

func quote(s string) string { return "'" + s + "'" }

const probeScript = `import importlib.util, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location("_flashcli_probe", path)
if spec is None or spec.loader is None:
    raise SystemExit("cannot create extension spec")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except ImportError as exc:
    msg = str(exc)
    if "Python version mismatch" in msg or "interpreter version is incompatible" in msg:
        print(msg, file=sys.stderr)
        raise SystemExit(2)
`

// ProbeRuntimeABI load-tests each tagged .so with its filename Python ABI.
// pythonFor returns an interpreter path for a 3-digit minor (e.g. "310").
func ProbeRuntimeABI(root string, runtimeMap map[string]string, pythonFor func(minor string) (string, bool)) []string {
	var errors []string
	for envKey, rel := range runtimeMap {
		dir := filepath.Join(root, filepath.FromSlash(strings.Trim(rel, "/")))
		if info, err := os.Stat(dir); err != nil || !info.IsDir() {
			continue
		}
		for _, name := range soFiles(dir) {
			parsed, ok := ParseFilename(name, envKey)
			if !ok || parsed.PythonMinor == "" {
				continue
			}
			python, found := pythonFor(parsed.PythonMinor)
			if !found {
				errors = append(errors, name+": no Python 3."+parsed.PythonMinor[1:]+" interpreter found to verify (set FLASHCLI_PY"+parsed.PythonMinor+"_BIN)")
				continue
			}
			if err := runProbe(python, filepath.Join(dir, name)); err != nil {
				errors = append(errors, name+": "+err.Error())
			}
		}
	}
	sort.Strings(errors)
	return errors
}

func runProbe(python, so string) error {
	cmd := exec.Command(python, "-c", probeScript, so)
	out, err := cmd.CombinedOutput()
	if err == nil {
		return nil
	}
	text := string(out)
	if strings.Contains(text, "Python version mismatch") || strings.Contains(text, "interpreter version is incompatible") {
		return fmt.Errorf("Python ABI does not match filename tag: %s", firstLine(text))
	}
	if strings.Contains(text, "GLIBCXX_") || strings.Contains(text, "GLIBC_") || strings.Contains(text, "CXXABI_") {
		return fmt.Errorf("host ABI too old: %s", firstLine(text))
	}
	// CUDA runtime / generic load failures are environment issues, not bundle errors
	// (mirrors native_validate.probe_native_so_abi returning None).
	lower := strings.ToLower(text)
	for _, marker := range []string{"libcublas", "libcudart", "libcuda", "cannot open shared object"} {
		if strings.Contains(lower, marker) {
			return nil
		}
	}
	if strings.Contains(text, "invalid ELF") || strings.Contains(text, "not an ELF") || strings.Contains(text, "Exec format error") {
		return fmt.Errorf("invalid ELF: %s", firstLine(text))
	}
	return nil
}

func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i]
	}
	return s
}
