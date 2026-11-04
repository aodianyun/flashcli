package system

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Status is the result of checking one required capability.
type Status struct {
	Capability Capability
	Present    bool
	Checked    bool
	Detail     string
}

// Check inspects the requested capabilities. python is the bundle venv
// interpreter, or empty when the venv has not been prepared yet.
func Check(ctx context.Context, requires []string, python string) ([]Status, error) {
	caps, err := Parse(requires)
	if err != nil {
		return nil, err
	}
	out := make([]Status, 0, len(caps))
	for _, cap := range caps {
		switch cap {
		case CCompiler:
			tool := firstTool("cc", "gcc", "clang")
			out = append(out, Status{
				Capability: cap,
				Checked:    true,
				Present:    tool != "",
				Detail:     tool,
			})
		case CXXCompiler:
			tool := firstTool("c++", "g++", "clang++")
			out = append(out, Status{
				Capability: cap,
				Checked:    true,
				Present:    tool != "",
				Detail:     tool,
			})
		case PythonHeaders:
			if python == "" {
				out = append(out, Status{
					Capability: cap,
					Checked:    false,
					Detail:     "not checked (bundle venv not ready)",
				})
				continue
			}
			ok, detail := checkPythonHeaders(ctx, python)
			out = append(out, Status{
				Capability: cap,
				Checked:    true,
				Present:    ok,
				Detail:     detail,
			})
		default:
			return nil, fmt.Errorf("unsupported system capability %q", cap)
		}
	}
	return out, nil
}

// Missing returns checked capabilities that are not present.
func Missing(statuses []Status) []Capability {
	var out []Capability
	for _, s := range statuses {
		if s.Checked && !s.Present {
			out = append(out, s.Capability)
		}
	}
	return out
}

func firstTool(names ...string) string {
	for _, name := range names {
		if path, err := exec.LookPath(name); err == nil {
			return path
		}
	}
	return ""
}

func checkPythonHeaders(ctx context.Context, python string) (bool, string) {
	const script = `import json, sysconfig
p = sysconfig.get_paths()
print(json.dumps({"include": p.get("include", ""), "platinclude": p.get("platinclude", "")}))`
	cmd := exec.CommandContext(ctx, python, "-c", script)
	out, err := cmd.Output()
	if err != nil {
		return false, "cannot query sysconfig include paths"
	}
	var paths map[string]string
	if err := json.Unmarshal(out, &paths); err != nil {
		return false, "invalid sysconfig output"
	}
	seen := map[string]bool{}
	for _, key := range []string{"include", "platinclude"} {
		dir := strings.TrimSpace(paths[key])
		if dir == "" || seen[dir] {
			continue
		}
		seen[dir] = true
		if info, err := os.Stat(filepath.Join(dir, "Python.h")); err == nil && !info.IsDir() {
			return true, filepath.Join(dir, "Python.h")
		}
	}
	return false, "Python.h not found in sysconfig include paths"
}
