package manifest

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// serveStaticScript inspects one Python serve module without importing it or
// creating a venv. It only understands directly defined classes; imported,
// inherited, or dynamic classes are skipped and remain the runtime's job.
const serveStaticScript = `
import ast, json, sys

path, attr, caps = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
required = set()
if "openai.chat" in caps or "openai.completions" in caps or "openai.responses" in caps or "anthropic.messages" in caps:
    required.update(("chat", "chat_stream"))
if "openai.embeddings" in caps:
    required.add("embed")
if "openai.moderations" in caps:
    required.add("moderate")
if "openai.audio.transcriptions" in caps or "openai.audio.translations" in caps:
    required.add("transcribe")
if "openai.audio.speech" in caps:
    required.add("speech")
if any(c.startswith("openai.images.") for c in caps):
    required.add("generate_images")
if "openai.videos" in caps:
    required.update(("create_video", "list_videos", "get_video", "download_video", "delete_video"))
if "anthropic.count_tokens" in caps:
    required.add("count_tokens")

try:
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
except SyntaxError as exc:
    print(json.dumps({"error": f"{path}: {exc.msg} (line {exc.lineno})"}))
    raise SystemExit(0)

cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == attr), None)
if cls is None:
    print(json.dumps({"skip": "class not found (imported or dynamic)"}))
    raise SystemExit(0)
bases = [ast.unparse(base) for base in cls.bases]
if any(base not in ("object", "") for base in bases):
    print(json.dumps({"skip": "class uses inheritance"}))
    raise SystemExit(0)

methods = set()
for node in cls.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        methods.add(node.name)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                methods.add(target.id)
if "__getattr__" in methods or "__getattribute__" in methods:
    print(json.dumps({"skip": "class is dynamic"}))
    raise SystemExit(0)

if "openai.realtime" in caps and "realtime_session" not in methods:
    required.update(("chat", "chat_stream"))
missing = sorted(required.difference(methods))
print(json.dumps({"missing": missing}))
`

type serveStaticResult struct {
	Missing []string `json:"missing"`
	Skip    string   `json:"skip"`
	Error   string   `json:"error"`
}

// ValidateServeMethods performs a best-effort AST check of declared capability
// methods for directly defined Python ServeEngine classes. It never imports the
// bundle or creates a venv, and silently skips when no Python interpreter is
// available or the class is imported/inherited/dynamic. Runtime loading remains
// authoritative.
func ValidateServeMethods(m *Manifest) []string {
	if m == nil {
		return nil
	}
	python, prefix, ok := staticPython()
	if !ok {
		return nil
	}
	type check struct {
		label string
		spec  *EntrySpec
	}
	var checks []check
	checks = append(checks, check{"entry.serve", m.EntryServe})
	if m.FormatVersion >= FormatVersionV4 {
		for _, key := range m.EnvironmentKeys() {
			env, err := m.ApplyEnv(key)
			if err != nil {
				continue
			}
			checks = append(checks, check{"environments." + key + ".entry.serve", env.EntryServe})
		}
	}
	variants := variantBlocksRaw(m)
	names := make([]string, 0, len(variants))
	for name := range variants {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		checks = append(checks, check{"variants." + name + ".entry.serve", m.EntryFor("serve", name)})
	}

	seen := map[string]bool{}
	var errors []string
	for _, item := range checks {
		spec := item.spec
		if spec == nil || spec.Kind != "python" || spec.Mode != "engine" {
			continue
		}
		key := spec.Module + "|" + spec.Attr + "|" + strings.Join(spec.EffectiveServeCapabilities(), ",")
		if seen[key] {
			continue
		}
		seen[key] = true
		file := filepath.Join(m.Root, filepath.FromSlash(strings.ReplaceAll(spec.Module, ".", "/"))+".py")
		if _, err := os.Stat(file); err != nil {
			continue // validateEntryFiles already reports a missing module
		}
		caps, err := json.Marshal(spec.EffectiveServeCapabilities())
		if err != nil {
			continue
		}
		args := append(append([]string{}, prefix...), "-c", serveStaticScript, file, spec.Attr, string(caps))
		cmd := exec.Command(python, args...)
		out, err := cmd.Output()
		if err != nil {
			continue // helper failure must not make a valid bundle fail
		}
		var result serveStaticResult
		if err := json.Unmarshal(out, &result); err != nil {
			continue
		}
		if result.Error != "" {
			errors = append(errors, fmt.Sprintf("%s: %s", item.label, result.Error))
			continue
		}
		if len(result.Missing) > 0 {
			errors = append(errors, fmt.Sprintf(
				"%s: %s:%s is missing methods %s required by capabilities %s",
				item.label,
				spec.Module,
				spec.Attr,
				strings.Join(result.Missing, ", "),
				strings.Join(spec.EffectiveServeCapabilities(), ", "),
			))
		}
	}
	return errors
}

func staticPython() (string, []string, bool) {
	if value := strings.TrimSpace(os.Getenv("FLASHCLI_PYTHON")); value != "" {
		if path, err := exec.LookPath(value); err == nil {
			return path, nil, true
		}
	}
	for _, name := range []string{"python3", "python"} {
		if path, err := exec.LookPath(name); err == nil {
			return path, nil, true
		}
	}
	if path, err := exec.LookPath("py"); err == nil {
		return path, []string{"-3"}, true
	}
	return "", nil, false
}
