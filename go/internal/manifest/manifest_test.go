package manifest

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fixturesDir(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..", "..", "tests", "conformance", "fixtures")
}

func TestFixtureExecutionOK(t *testing.T) {
	cases := []struct {
		fixture string
		kind    string
	}{
		{"python_echo", "python"},
		{"exec_echo", "native-exec"},
		{"abi_echo", "native-abi"},
	}
	for _, tc := range cases {
		t.Run(tc.fixture, func(t *testing.T) {
			m, err := Load(filepath.Join(fixturesDir(t), tc.fixture))
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if m.EntryRun == nil {
				t.Fatal("expected run capability")
			}
			if m.EntryRun.Kind != tc.kind {
				t.Fatalf("kind = %q, want %q", m.EntryRun.Kind, tc.kind)
			}
			if errs := ValidateExecution(m); len(errs) != 0 {
				t.Fatalf("ValidateExecution = %v, want none", errs)
			}
		})
	}
}

func baseData(entry map[string]any) map[string]any {
	return map[string]any{
		"format":           Format,
		"format_version":   float64(FormatVersion),
		"protocol_version": float64(ProtocolVersion),
		"name":             "t",
		"python_abi":       "310",
		"entry":            entry,
		"runtime":          map[string]any{"sm89-cu124-linux-x86_64-py310": "runtime/x"},
	}
}

func TestUnknownKindRejected(t *testing.T) {
	m, err := LoadData(baseData(map[string]any{"run": map[string]any{"kind": "wasm"}}), "/tmp")
	if err != nil {
		t.Fatalf("LoadData: %v", err)
	}
	if errs := ValidateExecution(m); len(errs) == 0 {
		t.Fatal("expected unknown kind error")
	}
}

func TestNativeExecRequiresVersion(t *testing.T) {
	_, err := LoadData(baseData(map[string]any{
		"run": map[string]any{"kind": "native-exec", "native": map[string]any{"command": []any{"x"}}},
	}), "/tmp")
	if err == nil {
		t.Fatal("expected exec_protocol_version error")
	}
}

func TestNativeABIRequiresVersion(t *testing.T) {
	_, err := LoadData(baseData(map[string]any{
		"run": map[string]any{"kind": "native-abi", "native": map[string]any{"library": "lib.so"}},
	}), "/tmp")
	if err == nil {
		t.Fatal("expected runtime_abi_version error")
	}
}

func TestStrayNativeVersionRejected(t *testing.T) {
	data := baseData(map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}})
	data["exec_protocol_version"] = float64(ExecProtocolVersion)
	if _, err := LoadData(data, "/tmp"); err == nil {
		t.Fatal("expected stray exec_protocol_version error")
	}
}

func TestNativeExecMissingCommand(t *testing.T) {
	data := baseData(map[string]any{
		"run": map[string]any{"kind": "native-exec", "native": map[string]any{}},
	})
	data["exec_protocol_version"] = float64(ExecProtocolVersion)
	m, err := LoadData(data, "/tmp")
	if err != nil {
		t.Fatalf("LoadData: %v", err)
	}
	if errs := ValidateExecution(m); len(errs) == 0 {
		t.Fatal("expected missing command error")
	}
}

func TestNativeSpecInheritanceAndOverride(t *testing.T) {
	data := baseData(map[string]any{
		"kind":   "native-abi",
		"native": map[string]any{"library": "lib.so", "preload": []any{"a.so"}},
		"run":    map[string]any{"kind": "native-abi", "native": map[string]any{"config": map[string]any{"p": float64(1)}}},
	})
	data["runtime_abi_version"] = float64(RuntimeABIVersion)
	m, err := LoadData(data, "/tmp")
	if err != nil {
		t.Fatalf("LoadData: %v", err)
	}
	if m.EntryRun.Native["library"] != "lib.so" {
		t.Fatalf("inherited library missing: %v", m.EntryRun.Native)
	}
	if _, ok := m.EntryRun.Native["config"]; !ok {
		t.Fatalf("capability config missing: %v", m.EntryRun.Native)
	}
}

func TestResolveVariant(t *testing.T) {
	plain := baseData(map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}})
	if _, err := LoadData(plain, "/tmp"); err != nil {
		t.Fatal(err)
	}
	mp, _ := LoadData(plain, "/tmp")
	if v, err := ResolveVariant(mp, ""); err != nil || v != "" {
		t.Fatalf("no-variant empty: %q %v", v, err)
	}
	if v, err := ResolveVariant(mp, "x"); err != nil || v != "x" {
		t.Fatalf("no-variant named: %q %v", v, err)
	}

	multi := baseData(map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}})
	multi["variants"] = map[string]any{"qwen3": map[string]any{}, "qwen36": map[string]any{}}
	mm, err := LoadData(multi, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ResolveVariant(mm, "qwen36"); err != nil {
		t.Fatalf("known variant: %v", err)
	}
	if _, err := ResolveVariant(mm, ""); err == nil || !strings.Contains(err.Error(), "add @variant") {
		t.Fatalf("missing variant should error: %v", err)
	}
	if _, err := ResolveVariant(mm, "qwen359"); err == nil || !strings.Contains(err.Error(), "Unknown model variant") {
		t.Fatalf("unknown variant should error: %v", err)
	}
}

func TestValidateFullBundleWithNative(t *testing.T) {
	root := t.TempDir()
	envKey := "sm89-cu124-linux-x86_64-py310"
	data := map[string]any{
		"format": Format, "format_version": float64(FormatVersion), "protocol_version": float64(ProtocolVersion),
		"name": "demo", "python_abi": "310",
		"entry":               map[string]any{"run": map[string]any{"module": "run", "attr": "RunEngine"}},
		"runtime":             map[string]any{envKey: "runtime/" + envKey},
		"python_dependencies": map[string]any{"pip": []any{}},
		"run_options":         []any{map[string]any{"name": "prompt", "help": "x"}},
		"weights":             map[string]any{"source": "huggingface", "repo": "o/r"},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, Filename), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "run.py"), []byte("class RunEngine: pass\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "flash_rt"), 0o755); err != nil {
		t.Fatal(err)
	}
	nativeDir := filepath.Join(root, "runtime", envKey)
	if err := os.MkdirAll(nativeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nativeDir, "flash_rt_kernels-dev-"+envKey+".so"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	m, err := Load(root)
	if err != nil {
		t.Fatal(err)
	}
	if errs := Validate(m); len(errs) != 0 {
		t.Fatalf("Validate errors = %v", errs)
	}
}
