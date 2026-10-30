package manifest

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

const FormatVersionV4 = 4

// Environments returns the v4 environment overlay keys.
func (m *Manifest) EnvironmentKeys() []string {
	keys := make([]string, 0, len(m.Environments))
	for k := range m.Environments {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// ApplyEnv returns a new manifest with the selected v4 environment overlay
// applied. v3 manifests are returned unchanged.
func (m *Manifest) ApplyEnv(envKey string) (*Manifest, error) {
	if m.FormatVersion < FormatVersionV4 {
		return m, nil
	}
	overlay, ok := m.Environments[envKey]
	if !ok {
		return nil, fmt.Errorf("Bundle %q has no environment %q (choose from: %s)", m.Name, envKey, strings.Join(m.EnvironmentKeys(), ", "))
	}
	raw := cloneMap(m.Raw)
	merged, _ := mergeV4(raw, overlay).(map[string]any)
	return buildV4Manifest(merged, m.Root, m.Name, m.Description, m.Environments)
}

func loadV4(data map[string]any, root string) (*Manifest, error) {
	if str(data["format"]) != Format {
		return nil, fmt.Errorf("Unsupported bundle format: %q (expected %q)", data["format"], Format)
	}
	version, err := intFromAny(data["format_version"])
	if err != nil || version != FormatVersionV4 {
		return nil, fmt.Errorf("Unsupported format_version %v (expected %d)", data["format_version"], FormatVersionV4)
	}
	if _, ok := data["variants"]; ok {
		return nil, fmt.Errorf("Bundle %q uses variants, which are not supported by format_version 4", str(data["name"]))
	}
	defaults, ok := data["defaults"].(map[string]any)
	if !ok || len(defaults) == 0 {
		return nil, fmt.Errorf("Bundle %q format_version 4 requires a non-empty defaults object", str(data["name"]))
	}
	envRaw, ok := data["environments"].(map[string]any)
	if !ok || len(envRaw) == 0 {
		return nil, fmt.Errorf("Bundle %q format_version 4 requires a non-empty environments object", str(data["name"]))
	}

	raw := cloneMap(defaults)
	for key, value := range data {
		if key == "defaults" || key == "environments" {
			continue
		}
		raw[key] = cloneValue(value)
	}
	runtimeMap := map[string]any{}
	envs := map[string]map[string]any{}
	for key, value := range envRaw {
		block, ok := value.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("environments.%s must be an object", key)
		}
		runtimePath := strings.TrimSpace(str(block["runtime"]))
		runtimeMap[key] = runtimePath
		overlay := cloneMap(block)
		delete(overlay, "runtime")
		envs[key] = overlay
	}
	if err := validateEnvironmentFallbacks(envs); err != nil {
		return nil, err
	}
	raw["runtime"] = runtimeMap
	return buildV4Manifest(raw, root, str(data["name"]), str(data["description"]), envs)
}

func buildV4Manifest(raw map[string]any, root, name, description string, envs map[string]map[string]any) (*Manifest, error) {
	if name = strings.TrimSpace(name); name == "" {
		name = strings.TrimSpace(str(raw["name"]))
	}
	if name == "" {
		name = "bundle"
	}
	entryKind := "python"
	var entryNative map[string]any
	if entry, ok := raw["entry"].(map[string]any); ok {
		entryKind = strings.ToLower(strings.TrimSpace(str(entry["kind"])))
		if entryKind == "" {
			entryKind = "python"
		}
		if n, ok := entry["native"].(map[string]any); ok {
			entryNative = n
		}
	}
	entryMap, _ := raw["entry"].(map[string]any)
	entryRun := entrySpecFromMap(asMap(entryMap, "run"), entryKind, entryNative)
	entryServe := entrySpecFromMap(asMap(entryMap, "serve"), entryKind, entryNative)
	m := &Manifest{
		Root: root, Name: name, Description: description,
		FormatVersion: FormatVersionV4, Environments: envs,
		EntryRun: entryRun, EntryServe: entryServe, Raw: raw,
	}
	if entryRun != nil {
		m.Capabilities = append(m.Capabilities, "run")
	}
	if entryServe != nil {
		m.Capabilities = append(m.Capabilities, "serve")
	}
	if err := requireV4(m); err != nil {
		return nil, err
	}
	return m, nil
}

func requireV4(m *Manifest) error {
	if str(m.Raw["format"]) != Format {
		return fmt.Errorf("Unsupported bundle format: %q (expected %q)", m.Raw["format"], Format)
	}
	if v, err := intField(m, "format_version"); err != nil || v != FormatVersionV4 {
		return fmt.Errorf("Unsupported format_version %v (expected %d)", m.Raw["format_version"], FormatVersionV4)
	}
	if _, ok := m.Raw["protocol_version"]; !ok {
		return fmt.Errorf("Bundle %q missing required field protocol_version (current flashcli-bundle protocol is %d)", m.Name, ProtocolVersion)
	}
	pv, err := intField(m, "protocol_version")
	if err != nil {
		return err
	}
	if pv != ProtocolVersion {
		return fmt.Errorf("Bundle %q protocol_version=%d does not match installed flashcli-bundle protocol %d", m.Name, pv, ProtocolVersion)
	}
	if _, ok := m.Raw["runtime"].(map[string]any); !ok || len(m.RuntimeMap()) == 0 {
		return fmt.Errorf("Bundle %q missing runtime map", m.Name)
	}
	return CheckExecutionVersions(m)
}

func intFromAny(v any) (int, error) {
	switch n := v.(type) {
	case float64:
		return int(n), nil
	case int:
		return n, nil
	case json.Number:
		i, err := n.Int64()
		return int(i), err
	default:
		return 0, fmt.Errorf("expected integer, got %T", v)
	}
}

func cloneMap(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for k, v := range in {
		out[k] = cloneValue(v)
	}
	return out
}

func cloneValue(v any) any {
	switch x := v.(type) {
	case map[string]any:
		return cloneMap(x)
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = cloneValue(item)
		}
		return out
	default:
		return v
	}
}

func mergeV4(base, overlay any) any {
	bm, ok := base.(map[string]any)
	om, ok2 := overlay.(map[string]any)
	if !ok || !ok2 {
		return cloneValue(overlay)
	}
	out := cloneMap(bm)
	for k, v := range om {
		if existing, ok := out[k]; ok {
			out[k] = mergeV4(existing, v)
		} else {
			out[k] = cloneValue(v)
		}
	}
	return out
}
