package manifest

import "strings"

// deepMerge merges override into base: maps merge recursively, scalars/lists
// replace. base is not mutated.
func deepMerge(base, override map[string]any) map[string]any {
	out := make(map[string]any, len(base)+len(override))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range override {
		if ov, ok := v.(map[string]any); ok {
			if bv, ok := out[k].(map[string]any); ok {
				out[k] = deepMerge(bv, ov)
				continue
			}
		}
		out[k] = v
	}
	return out
}

// mergedEntryMap returns the top-level `entry` deep-merged with the resolved
// variant's optional `entry` override.
func (m *Manifest) mergedEntryMap(variant string) map[string]any {
	entryMap, _ := m.Raw["entry"].(map[string]any)
	if entryMap == nil {
		entryMap = map[string]any{}
	}
	if variant != "" {
		if block, ok := variantBlocksRaw(m)[variant]; ok {
			if ve, ok := block["entry"].(map[string]any); ok {
				entryMap = deepMerge(entryMap, ve)
			}
		}
	}
	return entryMap
}

// EntryFor returns the effective EntrySpec for a capability under a resolved
// variant. A variant's `entry` block deep-merges over the top-level `entry`
// (objects merge; scalars/lists replace), so a variant may switch the
// execution backend (kind/native) per capability. Returns nil when the
// capability is not enabled.
func (m *Manifest) EntryFor(capability, variant string) *EntrySpec {
	entryMap := m.mergedEntryMap(variant)
	kind := strings.ToLower(strings.TrimSpace(str(entryMap["kind"])))
	if kind == "" {
		kind = "python"
	}
	native := asMap(entryMap, "native")
	return entrySpecFromMap(asMap(entryMap, capability), kind, native)
}

// effectiveEntries returns every (capability, variant, spec) combination,
// including the default variant "" when a capability is enabled at top level.
func (m *Manifest) effectiveEntries() []struct {
	Cap     string
	Variant string
	Spec    *EntrySpec
} {
	var out []struct {
		Cap     string
		Variant string
		Spec    *EntrySpec
	}
	variants := []string{""}
	for name := range variantBlocksRaw(m) {
		variants = append(variants, name)
	}
	for _, v := range variants {
		for _, cap := range []string{"run", "serve"} {
			if spec := m.EntryFor(cap, v); spec != nil {
				out = append(out, struct {
					Cap     string
					Variant string
					Spec    *EntrySpec
				}{cap, v, spec})
			}
		}
	}
	return out
}
