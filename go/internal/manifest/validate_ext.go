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
	return m.NeedsPythonVenv()
}

func validatePythonDependencies(m *Manifest) []string {
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
			if r := mapString(block["weights_dir"], ""); r != "" {
				rel = r
			} else {
				rel = "checkpoint/" + variant
			}
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

func validateWeights(m *Manifest) []string {
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
		return errors
	}

	spec, _ := m.Raw["weights"].(map[string]any)
	if HasLocalWeights(m, "") {
		return nil
	}
	if len(spec) == 0 {
		return []string{"weights: no local checkpoint/ (or weights/) and no weights download spec in flashcli-bundle.json — add weights.repo or ship weights in the bundle"}
	}
	source := strings.ToLower(mapString(spec["source"], "huggingface"))
	switch source {
	case "huggingface", "modelscope":
		if mapString(spec["repo"], "") == "" {
			return []string{fmt.Sprintf("weights.repo is required when source is %s", source)}
		}
	case "url":
		if mapString(spec["url"], "") == "" {
			return []string{"weights.url is required when source is url"}
		}
	default:
		return []string{fmt.Sprintf("unsupported weights.source: %q", source)}
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

	if hasRun {
		ro, ok := m.Raw["run_options"].([]any)
		if !ok || len(ro) == 0 {
			errors = append(errors, "missing top-level run_options (required for entry.run)")
		} else {
			errors = append(errors, optionEntriesMissingHelp(ro, "run_options")...)
		}
	}
	if hasServe {
		so, ok := m.Raw["serve_options"].([]any)
		if !ok || len(so) == 0 {
			errors = append(errors, "missing top-level serve_options (required for entry.serve)")
		} else {
			errors = append(errors, optionEntriesMissingHelp(so, "serve_options")...)
		}
	}
	return errors
}

func validateBundleSpecifics(m *Manifest) []string {
	var errors []string
	if hasPythonEntry(m) {
		if info, err := os.Stat(filepath.Join(m.Root, "flash_rt")); err != nil || !info.IsDir() {
			errors = append(errors, "missing flash_rt/ Python tree")
		}
	}
	if m.Name == "groot_n17" {
		if _, err := os.Stat(filepath.Join(m.Root, "gr00t", "VENDOR.json")); err != nil {
			errors = append(errors, "missing vendored gr00t/ (run bundles/groot_n17/vendor_gr00t.sh or build.sh)")
		}
	}
	return errors
}
