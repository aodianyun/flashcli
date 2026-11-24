package manifest

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// serveStaticScript inspects one Python serve module without importing it or
// creating a venv. It only understands directly defined classes; imported,
// inherited, or dynamic classes are skipped and remain the runtime's job.
const serveStaticScript = `
import ast, json, sys

path, attr, caps_json, concurrency = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
caps = json.loads(caps_json)
chat_caps = {"openai.chat", "openai.completions", "openai.responses", "anthropic.messages"}
method_map = {
    "openai.embeddings": ("embed",),
    "openai.moderations": ("moderate",),
    "openai.audio.transcriptions": ("transcribe",),
    "openai.audio.translations": ("transcribe",),
    "openai.audio.speech": ("speech",),
    "openai.images.generations": ("generate_images",),
    "openai.images.edits": ("generate_images",),
    "openai.images.variations": ("generate_images",),
    "openai.videos": ("create_video", "list_videos", "get_video", "download_video", "delete_video"),
    "anthropic.count_tokens": ("count_tokens",),
}
gated_map = {
    "openai.embeddings": ("embed",),
    "openai.moderations": ("moderate",),
    "openai.audio.transcriptions": ("transcribe",),
    "openai.audio.translations": ("transcribe",),
    "openai.audio.speech": ("speech",),
    "openai.images.generations": ("generate_images",),
    "openai.images.edits": ("generate_images",),
    "openai.images.variations": ("generate_images",),
    "openai.videos": ("create_video",),
}

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

methods = {}
for node in cls.body:
    if isinstance(node, ast.FunctionDef):
        methods[node.name] = False
    elif isinstance(node, ast.AsyncFunctionDef):
        methods[node.name] = True
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                methods[target.id] = False
if "__getattr__" in methods or "__getattribute__" in methods:
    print(json.dumps({"skip": "class is dynamic"}))
    raise SystemExit(0)

needs_chat = any(cap in chat_caps for cap in caps)
if "openai.realtime" in caps and "realtime_session" not in methods:
    needs_chat = True

missing = []
if needs_chat:
    if not any(name in methods for name in ("chat", "chat_async")):
        missing.append("chat or chat_async")
    if not any(name in methods for name in ("chat_stream", "chat_stream_async")):
        missing.append("chat_stream or chat_stream_async")
for cap in caps:
    for name in method_map.get(cap, ()):
        if name not in methods:
            missing.append(name)
if missing:
    print(json.dumps({"missing": sorted(set(missing))}))
    raise SystemExit(0)

if concurrency <= 1:
    print(json.dumps({}))
    raise SystemExit(0)

gated = {}
if needs_chat:
    gated["chat"] = ("chat_async", "chat")
    gated["chat_stream"] = ("chat_stream_async", "chat_stream")
for cap in caps:
    for name in gated_map.get(cap, ()):
        gated[name] = (name,)
if "openai.realtime" in caps:
    if "realtime_session" in methods:
        gated["realtime_session"] = ("realtime_session",)
    else:
        gated["chat"] = ("chat_async", "chat")
        gated["chat_stream"] = ("chat_stream_async", "chat_stream")
not_async = sorted(
    name for name, aliases in gated.items()
    if not any(methods.get(alias) is True for alias in aliases)
)
print(json.dumps({"not_async": not_async}))
`

type serveStaticResult struct {
	Missing  []string `json:"missing"`
	NotAsync []string `json:"not_async"`
	Skip     string   `json:"skip"`
	Error    string   `json:"error"`
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
		key := spec.Module + "|" + spec.Attr + "|" + strings.Join(spec.EffectiveServeCapabilities(), ",") + "|" + strconv.Itoa(spec.EffectiveServeConcurrency())
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
		concurrency := spec.EffectiveServeConcurrency()
		args := append(append([]string{}, prefix...),
			"-c", serveStaticScript, file, spec.Attr, string(caps), strconv.Itoa(concurrency))
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
		if len(result.NotAsync) > 0 {
			errors = append(errors, fmt.Sprintf(
				"%s: serve.concurrency > 1 requires async methods; sync or missing: %s",
				item.label,
				strings.Join(result.NotAsync, ", "),
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
