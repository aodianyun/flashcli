package native

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const env = "sm89-cu124-linux-x86_64-py312"

func touch(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestParseStem(t *testing.T) {
	p, ok := ParseStem("flash_rt_kernels-v1.2.0-"+env, env)
	if !ok || p.ModuleBase != "flash_rt_kernels" || p.FlashrtABI != "v1.2.0" || p.PythonMinor != "312" {
		t.Fatalf("parsed = %+v ok=%v", p, ok)
	}
	legacy, ok := ParseStem("flash_rt_fa2-"+env, env)
	if !ok || legacy.FlashrtABI != "dev" {
		t.Fatalf("legacy = %+v ok=%v", legacy, ok)
	}
	if _, ok := ParseStem("libfoo-v1-"+env, env); ok {
		t.Fatal("non flash_rt module should not parse")
	}
}

func TestDiscoverModuleBases(t *testing.T) {
	dir := t.TempDir()
	touch(t, filepath.Join(dir, "flash_rt_kernels-v1.2.0-"+env+".so"))
	touch(t, filepath.Join(dir, "flash_rt_fa2-v1.2.0-"+env+".so"))
	touch(t, filepath.Join(dir, "random.so"))
	got := DiscoverModuleBases(dir, env)
	if strings.Join(got, ",") != "flash_rt_fa2,flash_rt_kernels" {
		t.Fatalf("modules = %v", got)
	}
}

func TestValidateRuntimeCellValid(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "runtime", env)
	touch(t, filepath.Join(dir, "flash_rt_kernels-v1.2.0-"+env+".so"))
	touch(t, filepath.Join(dir, "flash_rt_fa2-v1.2.0-"+env+".so"))
	if errs := ValidateRuntimeCell(root, env, dir); len(errs) != 0 {
		t.Fatalf("errors = %v", errs)
	}
}

func TestValidateRuntimeCellEmpty(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "runtime", env)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	errs := ValidateRuntimeCell(root, env, dir)
	if len(errs) == 0 || !strings.Contains(errs[0], "no recognized") {
		t.Fatalf("errors = %v", errs)
	}
}

func TestValidateRuntimeCellAllowsSharedBuildTag(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "runtime", env)
	touch(t, filepath.Join(dir, "flash_rt_kernels-v1.2.0-sm120-cu130-linux-x86_64-py312.so"))
	if errs := ValidateRuntimeCell(root, env, dir); len(errs) != 0 {
		t.Fatalf("errors = %v", errs)
	}
}

func TestValidateRuntimeMatrixMissingDir(t *testing.T) {
	root := t.TempDir()
	errs := ValidateRuntimeMatrix(root, map[string]string{env: "runtime/" + env})
	if len(errs) == 0 || !strings.Contains(errs[0], "missing") {
		t.Fatalf("errors = %v", errs)
	}
}

func script(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "py")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestProbeRuntimeABI(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "runtime", env)
	touch(t, filepath.Join(dir, "flash_rt_kernels-dev-"+env+".so"))
	runtimeMap := map[string]string{env: "runtime/" + env}

	okPy := script(t, "exit 0\n")
	if errs := ProbeRuntimeABI(root, runtimeMap, func(string) (string, bool) { return okPy, true }); len(errs) != 0 {
		t.Fatalf("ok probe errors = %v", errs)
	}

	errs := ProbeRuntimeABI(root, runtimeMap, func(string) (string, bool) { return "", false })
	joined := strings.Join(errs, "\n")
	if !strings.Contains(joined, "no Python") {
		t.Fatalf("missing interpreter errors = %v", errs)
	}

	badPy := script(t, "echo 'Python version mismatch' 1>&2\nexit 2\n")
	errs = ProbeRuntimeABI(root, runtimeMap, func(string) (string, bool) { return badPy, true })
	if !strings.Contains(strings.Join(errs, "\n"), "does not match filename tag") {
		t.Fatalf("abi mismatch errors = %v", errs)
	}
}

func TestValidateRuntimeMatrixSharedCell(t *testing.T) {
	root := t.TempDir()
	shared := filepath.Join(root, "runtime", "shared")
	touch(t, filepath.Join(shared, "flash_rt_kernels-v1.2.0-sm120-cu130-linux-x86_64-py312.so"))
	touch(t, filepath.Join(shared, "flash_rt_fa2-v1.2.0-sm120-cu130-linux-x86_64-py312.so"))
	rm := map[string]string{
		"env-a": "runtime/shared",
		"env-b": "runtime/shared/",
		"env-c": "",
	}
	if errs := ValidateRuntimeMatrix(root, rm); len(errs) != 0 {
		t.Fatalf("shared runtime errors = %v", errs)
	}
}

func TestValidateRuntimeMatrixSharedCellDeduplicatesErrors(t *testing.T) {
	root := t.TempDir()
	rm := map[string]string{
		"env-a": "runtime/missing",
		"env-b": "runtime/missing",
	}
	errs := ValidateRuntimeMatrix(root, rm)
	if len(errs) != 1 || !strings.Contains(errs[0], "missing runtime/missing") {
		t.Fatalf("shared missing cell errors = %v", errs)
	}
}

func TestProbeRuntimeABIProbesSharedCellOnce(t *testing.T) {
	root := t.TempDir()
	shared := filepath.Join(root, "runtime", "shared")
	touch(t, filepath.Join(shared, "flash_rt_kernels-dev-sm120-cu130-linux-x86_64-py312.so"))
	py := script(t, "exit 0\n")
	calls := 0
	rm := map[string]string{
		"env-a": "runtime/shared",
		"env-b": "runtime/shared",
	}
	errs := ProbeRuntimeABI(root, rm, func(minor string) (string, bool) {
		calls++
		return py, true
	})
	if len(errs) != 0 {
		t.Fatalf("probe errors = %v", errs)
	}
	if calls != 1 {
		t.Fatalf("probe calls = %d, want 1 for shared runtime", calls)
	}
}
