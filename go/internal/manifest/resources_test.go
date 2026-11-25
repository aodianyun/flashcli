package manifest

import (
	"strings"
	"testing"
)

func resourceFixture(envs []string, resources any) map[string]any {
	return resourceFixtureVersion(envs, resources, FormatVersionV4)
}

func resourceFixtureVersion(envs []string, resources any, version int) map[string]any {
	defaults := map[string]any{
		"python_abi": "312",
		"entry": map[string]any{
			"run": map[string]any{"kind": "python", "module": "run", "attr": "RunEngine"},
		},
	}
	if resources != nil {
		defaults["resources"] = resources
	}
	envMap := map[string]any{}
	for _, key := range envs {
		envMap[key] = map[string]any{"runtime": "runtime/" + key}
	}
	return map[string]any{
		"format": Format, "format_version": version, "protocol_version": 1,
		"name": "demo", "defaults": defaults, "environments": envMap,
	}
}

func loadResourceFixture(t *testing.T, envs []string, resources any) *Manifest {
	t.Helper()
	m, err := LoadData(resourceFixture(envs, resources), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func hasErrorContaining(errors []string, want string) bool {
	for _, e := range errors {
		if strings.Contains(e, want) {
			return true
		}
	}
	return false
}

func TestResourcesParsing(t *testing.T) {
	m := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, map[string]any{
		"min_vram_mib": 8192, "min_ram_mib": 16384, "gpu_count": 2,
	})
	r := m.Resources()
	if !r.Present || r.MinVRAMMiB != 8192 || r.MinRAMMiB != 16384 || r.GPUCount != 2 {
		t.Fatalf("resources = %+v", r)
	}
}

func TestResourcesDefaultGPUCount(t *testing.T) {
	m := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, map[string]any{
		"min_vram_mib": 4096,
	})
	if r := m.Resources(); r.GPUCount != 1 {
		t.Fatalf("gpu_count = %d, want 1", r.GPUCount)
	}
}

func TestResourcesRejectInvalidFields(t *testing.T) {
	cases := []struct {
		name      string
		resources any
		want      string
	}{
		{"device selection", map[string]any{"min_vram_mib": 8192, "gpu_ids": []any{0}}, "resources.gpu_ids is not allowed"},
		{"placement policy", map[string]any{"min_vram_mib": 8192, "placement": "spread"}, "resources.placement is not allowed"},
		{"zero gpu count", map[string]any{"min_vram_mib": 8192, "gpu_count": 0}, "gpu_count must be >= 1"},
		{"string vram", map[string]any{"min_vram_mib": "8192"}, "min_vram_mib must be an integer"},
		{"negative ram", map[string]any{"min_vram_mib": 8192, "min_ram_mib": -1}, "min_ram_mib must be >= 0"},
		{"non object", []any{1}, "resources must be an object"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, tc.resources)
			errs := Validate(m)
			if !hasErrorContaining(errs, tc.want) {
				t.Fatalf("errors = %v, want %q", errs, tc.want)
			}
		})
	}
}

func TestResourcesBlockRequiresMinVRAM(t *testing.T) {
	for _, resources := range []map[string]any{
		{},
		{"gpu_count": 1},
		{"min_ram_mib": 16384},
	} {
		m := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, resources)
		errs := Validate(m)
		if !hasErrorContaining(errs, "GPU runtime without resources.min_vram_mib") {
			t.Fatalf("resources=%v errors = %v", resources, errs)
		}
	}

	declared := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, map[string]any{"min_vram_mib": 8192})
	for _, e := range Validate(declared) {
		if strings.Contains(e, "min_vram_mib") {
			t.Fatalf("declared resources rejected: %v", e)
		}
	}
	if warnings := ValidateWarnings(declared); len(warnings) != 0 {
		t.Fatalf("declared resources warnings = %v", warnings)
	}

	cpuOnly := loadResourceFixture(t, []string{"cpu-linux-x86_64-py312"}, map[string]any{"min_ram_mib": 16384})
	for _, e := range Validate(cpuOnly) {
		if strings.Contains(e, "min_vram_mib") {
			t.Fatalf("CPU resources rejected for min_vram_mib: %v", e)
		}
	}
}

func TestResourcesLegacyWithoutBlockIsWarning(t *testing.T) {
	gpu := loadResourceFixture(t, []string{"sm89-cu124-linux-x86_64-py312"}, nil)
	if errs := Validate(gpu); hasErrorContaining(errs, "min_vram_mib") {
		t.Fatalf("legacy bundle must not fail validation: %v", errs)
	}
	if warnings := ValidateWarnings(gpu); !hasErrorContaining(warnings, "no resources block") {
		t.Fatalf("warnings = %v", warnings)
	}

	cpu := loadResourceFixture(t, []string{"cpu-linux-x86_64-py312"}, nil)
	if warnings := ValidateWarnings(cpu); len(warnings) != 0 {
		t.Fatalf("CPU bundle warnings = %v", warnings)
	}
}
