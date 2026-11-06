package manifest

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

func variantBlocksRaw(m *Manifest) map[string]map[string]any {
	raw, ok := m.Raw["variants"].(map[string]any)
	if !ok {
		return nil
	}
	out := map[string]map[string]any{}
	for k, v := range raw {
		if block, ok := v.(map[string]any); ok {
			out[k] = block
		}
	}
	return out
}

func mapString(v any, fallback string) string {
	if s, ok := v.(string); ok && strings.TrimSpace(s) != "" {
		return strings.TrimSpace(s)
	}
	return fallback
}

// ResolveVariant validates a ref's @variant against the manifest, mirroring
// flashcli_bundle.variants.resolve_bundle_variant:
//   - no variants: any/empty variant is returned as-is;
//   - variants present and variant empty: error (must specify @variant);
//   - variants present and unknown variant: error.
func ResolveVariant(m *Manifest, variant string) (string, error) {
	blocks := variantBlocksRaw(m)
	key := strings.TrimSpace(variant)
	if m.FormatVersion >= FormatVersionV4 && key != "" {
		return "", fmt.Errorf("Bundle %q format_version 4 does not support @variant; use separate bundles or environments", m.Name)
	}
	if len(blocks) == 0 {
		return key, nil
	}
	keys := make([]string, 0, len(blocks))
	for k := range blocks {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if key == "" {
		return "", fmt.Errorf("Bundle %q has variants; add @variant to the ref (choose from: %s)", m.Name, strings.Join(keys, ", "))
	}
	if _, ok := blocks[key]; !ok {
		return "", fmt.Errorf("Unknown model variant %q for bundle %q; choose from: %s", key, m.Name, strings.Join(keys, ", "))
	}
	return key, nil
}

// hasPythonEntry reports whether any capability (top-level or variant) uses the
// Python backend.
func hasPythonEntry(m *Manifest) bool {
	return hasPythonEntryForAnyEnvironment(m)
}

func validatePythonDependencies(m *Manifest) []string {
	if m.FormatVersion >= FormatVersionV4 {
		var errors []string
		for _, key := range m.EnvironmentKeys() {
			envManifest, err := m.ApplyEnv(key)
			if err != nil {
				errors = append(errors, err.Error())
				continue
			}
			if !envManifest.NeedsPythonVenv() {
				continue
			}
			if _, ok := envManifest.Raw["python_dependencies"].(map[string]any); !ok {
				errors = append(errors, fmt.Sprintf("environments.%s missing python_dependencies", key))
			}
		}
		return errors
	}
	if !hasPythonEntry(m) {
		return nil
	}
	if _, ok := m.Raw["python_dependencies"].(map[string]any); !ok {
		return []string{"flashcli-bundle.json missing python_dependencies"}
	}
	return nil
}

func validateRuntimeSuffix(m *Manifest) []string {
	abi := m.PythonABIOrEmpty()
	if abi == "" {
		// Native-only: runtime keys carry no "-py{NNN}" segment.
		return nil
	}
	var errors []string
	keys := make([]string, 0, len(m.RuntimeMap()))
	for k := range m.RuntimeMap() {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if strings.TrimSpace(m.RuntimeMap()[k]) == "" {
			continue
		}
		if _, fallback := m.Environments[k]["match"]; fallback {
			continue
		}
		if !strings.HasSuffix(k, "-py"+abi) {
			errors = append(errors, fmt.Sprintf("runtime key %q does not match python_abi=%q", k, abi))
		}
	}
	return errors
}

// HasLocalWeights reports whether a variant's weights dir has weight files.
func HasLocalWeights(m *Manifest, variant string) bool {
	rel := "checkpoint"
	if variants := variantBlocksRaw(m); len(variants) > 0 {
		if block, ok := variants[variant]; ok {
			rel = VariantWeightsRel(block, variant)
		}
	} else if r := mapString(m.Raw["weights_dir"], ""); r != "" {
		rel = r
	}
	entries, err := os.ReadDir(filepath.Join(m.Root, filepath.FromSlash(rel)))
	if err != nil {
		return false
	}
	for _, e := range entries {
		if !strings.HasPrefix(e.Name(), ".") {
			return true
		}
	}
	return false
}

// sameWeights reports whether two variant weights specs resolve to the same
// upstream (source/repo/revision), ignoring unknown keys.
func sameWeights(a, b map[string]any) bool {
	norm := func(spec map[string]any) [3]string {
		return [3]string{
			strings.ToLower(mapString(spec["source"], "huggingface")),
			strings.TrimSpace(mapString(spec["repo"], "")),
			strings.TrimSpace(mapString(spec["revision"], "main")),
		}
	}
	return norm(a) == norm(b)
}

func validateWeights(m *Manifest) []string {
	if m.FormatVersion >= FormatVersionV4 {
		var errors []string
		for _, key := range m.EnvironmentKeys() {
			envManifest, err := m.ApplyEnv(key)
			if err != nil {
				errors = append(errors, err.Error())
				continue
			}
			errors = append(errors, validateWeightsForManifest(envManifest, "environments."+key+": ")...)
		}
		return errors
	}
	variants := variantBlocksRaw(m)
	if len(variants) > 0 {
		names := make([]string, 0, len(variants))
		for name := range variants {
			names = append(names, name)
		}
		sort.Strings(names)
		var errors []string
		for _, name := range names {
			spec, _ := variants[name]["weights"].(map[string]any)
			if HasLocalWeights(m, name) {
				continue
			}
			if len(spec) == 0 {
				errors = append(errors, fmt.Sprintf("variants.%s: no local weights/ and no weights spec", name))
				continue
			}
			source := strings.ToLower(mapString(spec["source"], "huggingface"))
			if (source == "huggingface" || source == "modelscope") && mapString(spec["repo"], "") == "" {
				errors = append(errors, fmt.Sprintf("variants.%s.weights.repo is required", name))
			}
		}
		// Variants share on-disk weights when their checkpoint-relative dir
		// (weights_dir) is identical; require identical weights in that case.
		byRel := map[string][]string{}
		for _, name := range names {
			byRel[VariantWeightsRel(variants[name], name)] = append(byRel[VariantWeightsRel(variants[name], name)], name)
		}
		for rel, names2 := range byRel {
			if len(names2) < 2 {
				continue
			}
			var base map[string]any
			mismatch := false
			for _, name := range names2 {
				spec, _ := variants[name]["weights"].(map[string]any)
				if base == nil {
					base = spec
					continue
				}
				if !sameWeights(base, spec) {
					mismatch = true
					break
				}
			}
			if mismatch {
				errors = append(errors, fmt.Sprintf("variants %v share weights_dir %q but declare different weights — give them distinct weights_dir", names2, rel))
			}
		}
		return errors
	}

	return validateWeightsForManifest(m, "")
}

func validateWeightsForManifest(m *Manifest, prefix string) []string {
	spec, _ := m.Raw["weights"].(map[string]any)
	if HasLocalWeights(m, "") {
		return nil
	}
	if len(spec) == 0 {
		return []string{prefix + "weights: no local checkpoint/ (or weights/) and no weights download spec in flashcli-bundle.json — add weights.repo or ship weights in the bundle"}
	}
	source := strings.ToLower(mapString(spec["source"], "huggingface"))
	switch source {
	case "huggingface", "modelscope":
		if mapString(spec["repo"], "") == "" {
			return []string{prefix + fmt.Sprintf("weights.repo is required when source is %s", source)}
		}
	case "url":
		if mapString(spec["url"], "") == "" {
			return []string{prefix + "weights.url is required when source is url"}
		}
	default:
		return []string{prefix + fmt.Sprintf("unsupported weights.source: %q", source)}
	}
	return nil
}

func optionEntriesMissingHelp(block []any, prefix string) []string {
	var errors []string
	for _, item := range block {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name := mapString(obj["name"], "")
		if name == "" {
			continue
		}
		if mapString(obj["help"], "") == "" {
			errors = append(errors, fmt.Sprintf("%s.%s missing help", prefix, name))
		}
	}
	return errors
}

func validateOptions(m *Manifest) []string {
	if m.FormatVersion >= FormatVersionV4 {
		var errors []string
		for _, key := range m.EnvironmentKeys() {
			envManifest, err := m.ApplyEnv(key)
			if err != nil {
				errors = append(errors, err.Error())
				continue
			}
			errors = append(errors, validateOptionsForManifest(envManifest, "environments."+key)...)
		}
		return errors
	}
	hasRun := m.EntryRun != nil
	hasServe := m.EntryServe != nil
	variants := variantBlocksRaw(m)
	var errors []string

	if len(variants) > 0 {
		for _, key := range []string{"run_options", "serve_options"} {
			if block, ok := m.Raw[key].([]any); ok && len(block) > 0 {
				errors = append(errors, fmt.Sprintf("top-level %s is not allowed when variants are defined; declare options under each variants.<name>.", key))
			}
		}
		names := make([]string, 0, len(variants))
		for name := range variants {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			block := variants[name]
			if hasRun {
				ro, ok := block["run_options"].([]any)
				if !ok || len(ro) == 0 {
					errors = append(errors, fmt.Sprintf("variants.%s missing run_options (required for entry.run)", name))
				} else {
					errors = append(errors, optionEntriesMissingHelp(ro, fmt.Sprintf("variants.%s.run_options", name))...)
				}
			}
			if hasServe {
				so, ok := block["serve_options"].([]any)
				if !ok || len(so) == 0 {
					errors = append(errors, fmt.Sprintf("variants.%s missing serve_options (required for entry.serve)", name))
				} else {
					errors = append(errors, optionEntriesMissingHelp(so, fmt.Sprintf("variants.%s.serve_options", name))...)
				}
			}
		}
		return errors
	}

	return validateOptionsForManifest(m, "top-level")
}

func validateOptionsForManifest(m *Manifest, label string) []string {
	var errors []string
	if m.EntryRun != nil {
		ro, ok := m.Raw["run_options"].([]any)
		if !ok || len(ro) == 0 {
			errors = append(errors, fmt.Sprintf("missing %s run_options (required for entry.run)", label))
		} else {
			errors = append(errors, optionEntriesMissingHelp(ro, "run_options")...)
		}
	}
	if m.EntryServe != nil {
		so, ok := m.Raw["serve_options"].([]any)
		if !ok || len(so) == 0 {
			errors = append(errors, fmt.Sprintf("missing %s serve_options (required for entry.serve)", label))
		} else {
			errors = append(errors, optionEntriesMissingHelp(so, "serve_options")...)
		}
	}
	return errors
}

func validateBundleSpecifics(m *Manifest) []string {
	var errors []string
	if m.Name == "groot_n17" {
		if _, err := os.Stat(filepath.Join(m.Root, "gr00t", "VENDOR.json")); err != nil {
			errors = append(errors, "missing vendored gr00t/ (run bundles/groot_n17/vendor_gr00t.sh or build.sh)")
		}
	}
	return errors
}

// hasPythonEntryForAnyEnvironment reports whether any capability, including
// v4 environment overrides, uses the Python backend.
func hasPythonEntryForAnyEnvironment(m *Manifest) bool {
	if m.NeedsPythonVenv() {
		return true
	}
	if m.FormatVersion < FormatVersionV4 {
		return false
	}
	for _, key := range m.EnvironmentKeys() {
		envManifest, err := m.ApplyEnv(key)
		if err != nil {
			continue
		}
		if envManifest.NeedsPythonVenv() {
			return true
		}
	}
	return false
}

// validateEntryFiles checks every effective Python entry module, including v4
// per-environment overrides. Entry modules are relative to the bundle root.
func validateEntryFiles(m *Manifest) []string {
	var errors []string
	seen := map[string]bool{}
	check := func(label string, spec *EntrySpec) {
		if spec == nil || spec.Kind != "python" {
			return
		}
		key := spec.Module
		if seen[key] {
			return
		}
		seen[key] = true
		path := filepath.Join(m.Root, filepath.FromSlash(strings.ReplaceAll(spec.Module, ".", "/"))+".py")
		if _, err := os.Stat(path); err != nil {
			errors = append(errors, fmt.Sprintf("%s module file not found: %s (module %q under %s)", label, path, spec.Module, m.Root))
		}
	}
	check("entry.run", m.EntryRun)
	check("entry.serve", m.EntryServe)
	if m.FormatVersion >= FormatVersionV4 {
		for _, key := range m.EnvironmentKeys() {
			envManifest, err := m.ApplyEnv(key)
			if err != nil {
				errors = append(errors, err.Error())
				continue
			}
			check("environments."+key+".entry.run", envManifest.EntryRun)
			check("environments."+key+".entry.serve", envManifest.EntryServe)
		}
	}
	return errors
}
