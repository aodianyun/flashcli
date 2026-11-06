package manifest

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func v4Fixture() map[string]any {
	return map[string]any{
		"format": Format, "format_version": 4, "protocol_version": 1,
		"name": "demo",
		"build": map[string]any{
			"flashrt_tag": "v0.2.0-39-g66b18eb7",
			"git_commit":  "66b18eb766e73e2fcad406bc622bd3bfd70664c1",
		},
		"defaults": map[string]any{
			"entry": map[string]any{
				"run": map[string]any{"kind": "python", "module": "run", "attr": "RunEngine"},
			},
			"python_abi": "312",
			"python_dependencies": map[string]any{
				"torch": map[string]any{"package": "torch", "index": "auto"},
				"pip":   []any{"numpy"},
			},
			"weights": map[string]any{"source": "huggingface", "repo": "org/demo", "revision": "main"},
		},
		"environments": map[string]any{
			"linux": map[string]any{
				"runtime": "runtime/linux",
				"python_dependencies": map[string]any{
					"torch": map[string]any{"package": "torch", "index": "cu128"},
					"pip":   []any{"numpy", "triton"},
				},
			},
			"windows": map[string]any{
				"runtime": "runtime/windows",
				"python_dependencies": map[string]any{
					"torch": map[string]any{"package": "torch", "index": "cu128"},
					"pip":   []any{"numpy"},
				},
			},
		},
	}
}

func TestLoadV4AndApplyEnv(t *testing.T) {
	m, err := LoadData(v4Fixture(), "/tmp/demo")
	if err != nil {
		t.Fatal(err)
	}
	if m.FormatVersion != 4 || len(m.RuntimeMap()) != 2 {
		t.Fatalf("manifest = %+v runtime=%v", m, m.RuntimeMap())
	}
	linux, err := m.ApplyEnv("linux")
	if err != nil {
		t.Fatal(err)
	}
	if linux.EntryRun == nil || linux.EntryRun.Module != "run" {
		t.Fatalf("linux entry = %+v", linux.EntryRun)
	}
	build, _ := linux.Raw["build"].(map[string]any)
	if build["flashrt_tag"] != "v0.2.0-39-g66b18eb7" || build["git_commit"] == "" {
		t.Fatalf("build provenance lost after ApplyEnv: %v", build)
	}
	deps := linux.PythonDependencies()
	pip, _ := deps["pip"].([]any)
	if len(pip) != 2 {
		t.Fatalf("linux pip = %v", pip)
	}
	win, err := m.ApplyEnv("windows")
	if err != nil {
		t.Fatal(err)
	}
	if len(win.PythonDependencies()["pip"].([]any)) != 1 {
		t.Fatalf("windows deps = %v", win.PythonDependencies())
	}
}

func TestV4RejectsVariant(t *testing.T) {
	data := v4Fixture()
	if _, err := LoadData(data, "/tmp/demo"); err != nil {
		t.Fatal(err)
	}
	m, _ := LoadData(data, "/tmp/demo")
	if _, err := ResolveVariant(m, "x"); err == nil {
		t.Fatal("v4 @variant must be rejected")
	}
}

func TestV4RejectsVariantsField(t *testing.T) {
	data := v4Fixture()
	data["variants"] = map[string]any{"x": map[string]any{}}
	if _, err := LoadData(data, "/tmp/demo"); err == nil {
		t.Fatal("v4 variants must be rejected")
	}
}

func TestV4AllowsRuntimeLessPythonEnvironment(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	envs["cpu"] = map[string]any{
		"match": map[string]any{
			"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "cpu",
		},
	}
	m, err := LoadData(data, "/tmp/demo")
	if err != nil {
		t.Fatalf("runtime-less Python environment must load: %v", err)
	}
	if _, ok := m.RuntimeMap()["cpu"]; !ok {
		t.Fatalf("runtime-less environment missing from map: %v", m.RuntimeMap())
	}
}

func TestV4RejectsAmbiguousFallback(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	envs["fallback-a"] = map[string]any{
		"match": map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia"},
	}
	envs["fallback-b"] = map[string]any{
		"match": map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia"},
	}
	if _, err := LoadData(data, "/tmp/demo"); err == nil || !strings.Contains(err.Error(), "ambiguous fallback") {
		t.Fatalf("ambiguous fallback must fail validation: %v", err)
	}
}

func TestV4AllowsDisjointSameSpecificityFallback(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	for _, vendor := range []string{"nvidia", "amd"} {
		envs["fallback-"+vendor] = map[string]any{
			"match": map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": vendor},
		}
	}
	if _, err := LoadData(data, "/tmp/demo"); err != nil {
		t.Fatalf("disjoint fallback must load: %v", err)
	}
}

func TestV4FallbackSpecificity(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	envs["nvidia-linux"] = map[string]any{
		"runtime": "runtime/fat",
		"match":   map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia"},
	}
	envs["linux"] = map[string]any{
		"runtime": "runtime/linux",
		"match":   map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312"},
	}
	m, err := LoadData(data, "/tmp/demo")
	if err != nil {
		t.Fatal(err)
	}
	key, err := m.ResolveEnvKey("sm120-cu130-linux-x86_64-py312")
	if err != nil {
		t.Fatal(err)
	}
	if key != "nvidia-linux" {
		t.Fatalf("resolved = %q", key)
	}
}

func TestV4SharedRuntimeAndRuntimeLessEnvironment(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	envs["nvidia-shared"] = map[string]any{
		"runtime": "runtime/shared",
		"match": map[string]any{
			"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia",
		},
	}
	envs["amd-shared"] = map[string]any{
		"runtime": "runtime/shared",
		"match": map[string]any{
			"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "amd",
		},
	}
	envs["cpu-fallback"] = map[string]any{
		"match": map[string]any{
			"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "cpu",
		},
	}
	m, err := LoadData(data, "/tmp/demo")
	if err != nil {
		t.Fatal(err)
	}
	rt := m.RuntimeMap()
	if rt["nvidia-shared"] != "runtime/shared" || rt["amd-shared"] != "runtime/shared" {
		t.Fatalf("shared runtime map = %v", rt)
	}
	if rt["cpu-fallback"] != "" {
		t.Fatalf("runtime-less environment must map to empty runtime: %v", rt)
	}
	key, err := m.ResolveEnvKey("sm120-cu130-linux-x86_64-py312")
	if err != nil || key != "nvidia-shared" {
		t.Fatalf("GPU fallback = %q, %v", key, err)
	}
	key, err = m.ResolveEnvKey("cpu-linux-x86_64-py312")
	if err != nil || key != "cpu-fallback" {
		t.Fatalf("CPU fallback = %q, %v", key, err)
	}
}

func TestValidateEnvironmentFallbacks(t *testing.T) {
	m := func(match map[string]any) map[string]any { return map[string]any{"match": match} }
	cases := []struct {
		name string
		envs map[string]map[string]any
		want string
	}{
		{
			name: "missing required dimension",
			envs: map[string]map[string]any{
				"x": m(map[string]any{"os": "linux", "arch": "x86_64"}),
			},
			want: "requires python_abi",
		},
		{
			name: "unsupported dimension",
			envs: map[string]map[string]any{
				"x": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "gpu": "x"}),
			},
			want: "unsupported dimension",
		},
		{
			name: "empty match",
			envs: map[string]map[string]any{
				"x": m(map[string]any{}),
			},
			want: "must not be empty",
		},
		{
			name: "same specificity list overlap",
			envs: map[string]map[string]any{
				"a": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": []any{"nvidia", "amd"}}),
				"b": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "amd"}),
			},
			want: "ambiguous fallback",
		},
		{
			name: "os aliases overlap",
			envs: map[string]map[string]any{
				"a": m(map[string]any{"os": "windows", "arch": "x86_64", "python_abi": "312"}),
				"b": m(map[string]any{"os": "win32", "arch": "x86_64", "python_abi": "312"}),
			},
			want: "ambiguous fallback",
		},
		{
			name: "arch aliases overlap",
			envs: map[string]map[string]any{
				"a": m(map[string]any{"os": "linux", "arch": "aarch64", "python_abi": "312"}),
				"b": m(map[string]any{"os": "linux", "arch": "arm64", "python_abi": "312"}),
			},
			want: "ambiguous fallback",
		},
		{
			name: "python abi prefix overlap",
			envs: map[string]map[string]any{
				"a": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312"}),
				"b": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "py312"}),
			},
			want: "ambiguous fallback",
		},
		{
			name: "same specificity disjoint lists",
			envs: map[string]map[string]any{
				"a": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": []any{"nvidia", "amd"}}),
				"b": m(map[string]any{"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": []any{"npu", "cpu"}}),
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateEnvironmentFallbacks(tc.envs)
			if tc.want == "" {
				if err != nil {
					t.Fatal(err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %v, want contains %q", err, tc.want)
			}
		})
	}
}

func TestValidateSystemRequirements(t *testing.T) {
	cases := []struct {
		name string
		val  any
		want string
	}{
		{
			name: "valid compiler and headers",
			val: map[string]any{
				"requires": []any{"c-compiler", "python-headers"},
			},
		},
		{
			name: "valid compiler only",
			val: map[string]any{
				"requires": []any{"c-compiler"},
			},
		},
		{
			name: "unknown token",
			val: map[string]any{
				"requires": []any{"c-compiler", "cuda-nvcc"},
			},
			want: "unsupported system capability",
		},
		{
			name: "duplicate token",
			val: map[string]any{
				"requires": []any{"c-compiler", "c-compiler"},
			},
			want: "duplicate system capability",
		},
		{
			name: "missing requires",
			val:  map[string]any{},
			want: "system.requires is required",
		},
		{
			name: "not an array",
			val:  map[string]any{"requires": "c-compiler"},
			want: "must be an array",
		},
		{
			name: "non-string item",
			val:  map[string]any{"requires": []any{"c-compiler", 1}},
			want: "only strings",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			data := v4Fixture()
			data["defaults"].(map[string]any)["system"] = tc.val
			m, err := LoadData(data, "/tmp/demo")
			if err != nil {
				t.Fatal(err)
			}
			errs := validateSystemRequirements(m)
			if tc.want == "" {
				if len(errs) != 0 {
					t.Fatalf("errors = %v", errs)
				}
				return
			}
			if len(errs) == 0 || !strings.Contains(strings.Join(errs, " "), tc.want) {
				t.Fatalf("errors = %v, want %q", errs, tc.want)
			}
		})
	}
}

func TestSystemRequiresPythonABIForHeaders(t *testing.T) {
	data := v4Fixture()
	delete(data["defaults"].(map[string]any), "python_abi")
	data["defaults"].(map[string]any)["system"] = map[string]any{
		"requires": []any{"python-headers"},
	}
	m, err := LoadData(data, "/tmp/demo")
	if err != nil {
		t.Fatal(err)
	}
	errs := validateSystemRequirements(m)
	if len(errs) == 0 || !strings.Contains(strings.Join(errs, " "), "requires python_abi") {
		t.Fatalf("errors = %v", errs)
	}
}

func writeBundleFile(t *testing.T, root, rel, body string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestV4AllowsPythonRuntimeCellWithoutNativeOrFlashRt(t *testing.T) {
	root := t.TempDir()
	envKey := "sm89-cu124-linux-x86_64-py312"
	data := map[string]any{
		"format": Format, "format_version": 4, "protocol_version": 1,
		"name": "demo",
		"defaults": map[string]any{
			"python_abi": "312",
			"python_dependencies": map[string]any{
				"torch": false,
				"pip":   []any{},
			},
			"run_options": []any{map[string]any{"name": "prompt", "help": "x"}},
			"weights":     map[string]any{"source": "huggingface", "repo": "org/demo"},
		},
		"environments": map[string]any{
			envKey: map[string]any{
				"runtime": envKey,
				"entry": map[string]any{
					"run": map[string]any{"module": envKey + ".run", "attr": "RunEngine"},
				},
			},
		},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, Filename), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	writeBundleFile(t, root, envKey+"/run.py", "class RunEngine: pass\n")

	m, err := Load(root)
	if err != nil {
		t.Fatal(err)
	}
	if errs := Validate(m); len(errs) != 0 {
		t.Fatalf("Validate errors = %v", errs)
	}
}

func TestV4ValidatesEnvironmentEntryFiles(t *testing.T) {
	root := t.TempDir()
	envA := "sm89-cu124-linux-x86_64-py312"
	envB := "sm120-cu130-linux-x86_64-py312"
	data := map[string]any{
		"format": Format, "format_version": 4, "protocol_version": 1,
		"name": "demo",
		"defaults": map[string]any{
			"python_abi": "312",
			"python_dependencies": map[string]any{
				"torch": false,
				"pip":   []any{},
			},
			"run_options": []any{map[string]any{"name": "prompt", "help": "x"}},
			"weights":     map[string]any{"source": "huggingface", "repo": "org/demo"},
		},
		"environments": map[string]any{
			envA: map[string]any{
				"runtime": envA,
				"entry":   map[string]any{"run": map[string]any{"module": envA + ".run", "attr": "RunEngine"}},
			},
			envB: map[string]any{
				"runtime": envB,
				"entry":   map[string]any{"run": map[string]any{"module": envB + ".run", "attr": "RunEngine"}},
			},
		},
	}
	blob, _ := json.Marshal(data)
	if err := os.WriteFile(filepath.Join(root, Filename), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	writeBundleFile(t, root, envA+"/run.py", "class RunEngine: pass\n")

	m, err := Load(root)
	if err != nil {
		t.Fatal(err)
	}
	errs := Validate(m)
	if len(errs) == 0 {
		t.Fatal("expected missing environment entry error")
	}
	joined := strings.Join(errs, "\n")
	if !strings.Contains(joined, envB+".run") {
		t.Fatalf("errors missing env B entry: %v", errs)
	}
}
