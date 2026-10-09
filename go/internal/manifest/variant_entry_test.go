package manifest

import (
	"strings"
	"testing"
)

func TestPythonABIConditional(t *testing.T) {
	native := map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"runtime_abi_version": float64(1), "name": "native_only",
		"entry":   map[string]any{"kind": "native-abi", "run": map[string]any{"kind": "native-abi"}, "serve": map[string]any{"kind": "native-abi"}},
		"runtime": map[string]any{"sm120-cu130-linux-x86_64": "runtime/sm120-cu130-linux-x86_64"},
	}
	m, err := LoadData(native, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	if m.NeedsPythonVenv() {
		t.Fatal("native-only bundle should not need a venv")
	}
	for _, e := range Validate(m) {
		if strings.Contains(e, "python_abi") {
			t.Fatalf("native-only bundle must not require python_abi: %s", e)
		}
	}

	py := map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"name":    "py_bundle",
		"entry":   map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime": map[string]any{"sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"},
	}
	m2, err := LoadData(py, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	if !m2.NeedsPythonVenv() {
		t.Fatal("python entry should need a venv")
	}
	found := false
	for _, e := range Validate(m2) {
		if strings.Contains(e, "python_abi") {
			found = true
		}
	}
	if !found {
		t.Fatal("python entry without python_abi should be rejected")
	}
}

func variantManifest(t *testing.T) *Manifest {
	t.Helper()
	data := map[string]any{
		"format": "flashcli-model-bundle", "format_version": float64(3), "protocol_version": float64(1),
		"runtime_abi_version": float64(1), "exec_protocol_version": float64(1),
		"name": "t",
		"entry": map[string]any{
			"kind":   "native-abi",
			"native": map[string]any{"library": "L", "session_library": "S"},
			"run":    map[string]any{"kind": "native-abi"},
			"serve":  map[string]any{"kind": "native-abi"},
		},
		"variants": map[string]any{
			"abi": map[string]any{},
			"exec": map[string]any{
				"entry": map[string]any{
					"kind":   "native-exec",
					"native": map[string]any{"command": []any{"bin/x"}},
					"run":    map[string]any{"kind": "native-exec"},
					"serve":  map[string]any{"kind": "native-exec"},
				},
			},
		},
		"runtime": map[string]any{"sm120-cu130-linux-x86_64": "runtime/sm120-cu130-linux-x86_64"},
	}
	m, err := LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestEntryForVariantOverride(t *testing.T) {
	m := variantManifest(t)
	cases := []struct {
		cap, variant, kind string
	}{
		{"run", "abi", "native-abi"},
		{"serve", "abi", "native-abi"},
		{"run", "exec", "native-exec"},
		{"serve", "exec", "native-exec"},
	}
	for _, c := range cases {
		spec := m.EntryFor(c.cap, c.variant)
		if spec == nil {
			t.Fatalf("%s@%s: nil spec", c.cap, c.variant)
		}
		if spec.Kind != c.kind {
			t.Fatalf("%s@%s: kind=%q want %q", c.cap, c.variant, spec.Kind, c.kind)
		}
	}
	// native config for exec inherits the shared block and merges command.
	exec := m.EntryFor("run", "exec")
	if exec.Native["command"] == nil {
		t.Fatalf("exec native command not merged: %v", exec.Native)
	}
	if exec.Native["library"] != "L" {
		t.Fatalf("exec should inherit entry-level native; got %v", exec.Native["library"])
	}
}

func TestCheckExecutionVersionsAcrossVariants(t *testing.T) {
	m := variantManifest(t)
	if err := CheckExecutionVersions(m); err != nil {
		t.Fatalf("both axes set should pass: %v", err)
	}
	// Drop exec_protocol_version: native-exec exists only under a variant.
	delete(m.Raw, "exec_protocol_version")
	if err := CheckExecutionVersions(m); err == nil {
		t.Fatal("expected failure: native-exec variant without exec_protocol_version")
	}
}
