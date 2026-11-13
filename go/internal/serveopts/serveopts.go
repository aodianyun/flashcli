// Package serveopts reads a bundle's manifest-declared serve options and
// converts user-supplied values into `flashcli serve` flags.
package serveopts

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// Spec is one manifest `serve_options` entry.
type Spec struct {
	Name      string `json:"name"`
	Flag      string `json:"flag"`
	Type      string `json:"type"`
	Default   any    `json:"default,omitempty"`
	Help      string `json:"help,omitempty"`
	Phase     string `json:"phase,omitempty"`
	HostLevel bool   `json:"host_level,omitempty"`
}

// FromManifest returns the effective serve options for a bundle variant.
// v4 environment overlays are expected to be applied to m already.
func FromManifest(m *manifest.Manifest, variant string) []Spec {
	if m == nil {
		return nil
	}
	key := "serve_options"
	var raw any = m.Raw[key]
	if variant != "" {
		if variants, ok := m.Raw["variants"].(map[string]any); ok {
			if block, ok := variants[variant].(map[string]any); ok {
				if v, ok := block[key]; ok {
					raw = v
				}
			}
		}
	}
	items, _ := raw.([]any)
	out := make([]Spec, 0, len(items))
	for _, item := range items {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name := text(obj["name"])
		if name == "" {
			continue
		}
		flag := text(obj["flag"])
		if flag == "" {
			flag = strings.ReplaceAll(name, "_", "-")
		}
		flag = strings.TrimLeft(flag, "-")
		typ := strings.ToLower(text(obj["type"]))
		switch typ {
		case "string", "integer", "float", "boolean":
		default:
			typ = "string"
		}
		spec := Spec{
			Name:  name,
			Flag:  flag,
			Type:  typ,
			Help:  text(obj["help"]),
			Phase: strings.ToLower(text(obj["phase"])),
		}
		switch strings.ToLower(flag) {
		case "host", "ip", "port":
			spec.HostLevel = true
		}
		if v, ok := obj["default"]; ok {
			spec.Default = v
		}
		out = append(out, spec)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Flag < out[j].Flag })
	return out
}

func text(v any) string {
	if v == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(v))
}

// Validate normalizes values and rejects unknown names or invalid types.
// An empty value means "use the bundle default" and is kept as an empty entry.
func Validate(specs []Spec, values map[string]string) (map[string]string, error) {
	byName := make(map[string]Spec, len(specs))
	for _, spec := range specs {
		byName[spec.Name] = spec
	}
	out := make(map[string]string, len(values))
	for name, value := range values {
		spec, ok := byName[name]
		if !ok {
			return nil, fmt.Errorf("unknown serve option %q", name)
		}
		value = strings.TrimSpace(value)
		if value == "" {
			out[name] = ""
			continue
		}
		normalized, err := normalizeValue(spec, value)
		if err != nil {
			return nil, err
		}
		out[name] = normalized
	}
	return out, nil
}

func normalizeValue(spec Spec, value string) (string, error) {
	switch spec.Type {
	case "integer":
		n, err := strconv.ParseInt(value, 10, 64)
		if err != nil {
			return "", fmt.Errorf("%s must be an integer: %q", spec.Name, value)
		}
		return strconv.FormatInt(n, 10), nil
	case "float":
		n, err := strconv.ParseFloat(value, 64)
		if err != nil {
			return "", fmt.Errorf("%s must be a number: %q", spec.Name, value)
		}
		return strconv.FormatFloat(n, 'g', -1, 64), nil
	case "boolean":
		switch strings.ToLower(value) {
		case "1", "true", "yes", "on":
			return "true", nil
		case "0", "false", "no", "off":
			return "false", nil
		default:
			return "", fmt.Errorf("%s must be true or false: %q", spec.Name, value)
		}
	default:
		return value, nil
	}
}

// Flags renders values as `--flag value` pairs in stable order. Unknown names
// (for example an option removed by a bundle update) are ignored; API writes
// still use Validate and reject them.
func Flags(specs []Spec, values map[string]string) ([]string, error) {
	args := make([]string, 0, len(values)*2)
	ordered := append([]Spec(nil), specs...)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].Flag < ordered[j].Flag })
	for _, spec := range ordered {
		if spec.HostLevel {
			continue
		}
		value, ok := values[spec.Name]
		if !ok {
			continue
		}
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		normalized, err := normalizeValue(spec, value)
		if err != nil {
			return nil, err
		}
		args = append(args, "--"+spec.Flag, normalized)
	}
	return args, nil
}
