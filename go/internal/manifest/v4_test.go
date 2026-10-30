package manifest

import (
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
