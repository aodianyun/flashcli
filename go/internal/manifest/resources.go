package manifest

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/preflight"
)

// Resources is the model-agnostic resource contract declared by a bundle.
// Bundles never select devices or placement; flashserver decides those.
type Resources struct {
	Present    bool
	MinVRAMMiB int64
	MinRAMMiB  int64
	GPUCount   int
}

// resourceFields is the complete allowed set. Anything else (device ids,
// CUDA_VISIBLE_DEVICES, placement policy, ...) is rejected by validation.
var resourceFields = map[string]bool{
	"min_vram_mib": true,
	"min_ram_mib":  true,
	"gpu_count":    true,
}

// Resources reads the merged `resources` block (v4 defaults are already
// flattened into Raw). Missing values use the spec defaults: gpu_count=1.
func (m *Manifest) Resources() Resources {
	r := Resources{GPUCount: 1}
	if m == nil {
		return r
	}
	block, ok := m.Raw["resources"].(map[string]any)
	if !ok || block == nil {
		return r
	}
	r.Present = true
	if v, ok := intValue(block["min_vram_mib"]); ok && v > 0 {
		r.MinVRAMMiB = v
	}
	if v, ok := intValue(block["min_ram_mib"]); ok && v > 0 {
		r.MinRAMMiB = v
	}
	if v, ok := intValue(block["gpu_count"]); ok && v > 0 {
		r.GPUCount = int(v)
	}
	return r
}

func intValue(v any) (int64, bool) {
	switch n := v.(type) {
	case float64:
		if n != float64(int64(n)) {
			return 0, false
		}
		return int64(n), true
	case int:
		return int64(n), true
	case int64:
		return n, true
	case json.Number:
		i, err := n.Int64()
		return i, err == nil
	default:
		return 0, false
	}
}

// validateResources rejects malformed fields and any attempt to encode device
// selection or placement. format_version 5 additionally requires
// min_vram_mib for a GPU runtime; format_version 4 is the legacy contract and
// only warns (so already-published bundles keep running).
func validateResources(m *Manifest) []string {
	strict := m.FormatVersion >= FormatVersionV5
	raw, exists := m.Raw["resources"]
	if !exists {
		if strict && hasGPURuntime(m) {
			return []string{fmt.Sprintf(
				"Bundle %q has a GPU runtime but no resources.min_vram_mib; format_version 5 requires it",
				m.Name)}
		}
		return nil
	}
	block, ok := raw.(map[string]any)
	if !ok {
		return []string{fmt.Sprintf("Bundle %q resources must be an object", m.Name)}
	}
	var errors []string
	for key, value := range block {
		if !resourceFields[key] {
			errors = append(errors, fmt.Sprintf(
				"Bundle %q resources.%s is not allowed: bundles declare resource requirements only, never devices or placement",
				m.Name, key))
			continue
		}
		v, ok := intValue(value)
		if !ok {
			errors = append(errors, fmt.Sprintf("Bundle %q resources.%s must be an integer, got %v", m.Name, key, value))
			continue
		}
		if key == "gpu_count" && v < 1 {
			errors = append(errors, fmt.Sprintf("Bundle %q resources.gpu_count must be >= 1", m.Name))
		}
		if key != "gpu_count" && v < 0 {
			errors = append(errors, fmt.Sprintf("Bundle %q resources.%s must be >= 0", m.Name, key))
		}
	}
	if strict && hasGPURuntime(m) && m.Resources().MinVRAMMiB == 0 {
		errors = append(errors, fmt.Sprintf(
			"Bundle %q has a GPU runtime but no resources.min_vram_mib; format_version 5 requires it",
			m.Name))
	}
	return errors
}

// ValidateWarnings reports advisories that do not fail validation. Legacy
// format_version 4 GPU bundles without min_vram_mib are admitted best-effort.
func ValidateWarnings(m *Manifest) []string {
	if m == nil || m.FormatVersion >= FormatVersionV5 {
		return nil
	}
	r := m.Resources()
	if r.Present && r.MinVRAMMiB > 0 {
		return nil
	}
	if !hasGPURuntime(m) {
		return nil
	}
	return []string{fmt.Sprintf(
		"Bundle %q is legacy format_version 4 and has no resources.min_vram_mib; flashserver will admit it without a declared VRAM requirement. New bundles should use format_version 5 and declare it",
		m.Name)}
}

func hasGPURuntime(m *Manifest) bool {
	for key := range m.RuntimeMap() {
		env, err := preflight.ParseEnvKey(key)
		if err != nil {
			continue
		}
		switch strings.ToLower(env.Vendor()) {
		case "", "cpu":
			if env.SM != "" || env.CudaTag != "" {
				return true
			}
		default:
			return true
		}
	}
	return false
}
