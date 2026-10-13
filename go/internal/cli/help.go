package cli

import (
	"fmt"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/manifest"
)

type optionSpec struct {
	Name    string
	Flag    string
	Type    string
	Default any
	Help    string
}

// bundleOptionSpecs returns run_options/serve_options for a variant.
func bundleOptionSpecs(m *manifest.Manifest, capability, variant string) []optionSpec {
	key := capability + "_options"
	var raw any
	if variants, ok := m.Raw["variants"].(map[string]any); ok && variant != "" {
		if block, ok := variants[variant].(map[string]any); ok {
			raw = block[key]
		}
	} else {
		raw = m.Raw[key]
	}
	list, _ := raw.([]any)
	var out []optionSpec
	for _, item := range list {
		obj, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name := strings.TrimSpace(strOf(obj["name"]))
		if name == "" {
			continue
		}
		flag := strings.TrimSpace(strOf(obj["flag"]))
		if flag == "" {
			flag = strings.ReplaceAll(name, "_", "-")
		}
		out = append(out, optionSpec{
			Name:    name,
			Flag:    strings.TrimLeft(flag, "-"),
			Type:    strOf(obj["type"]),
			Default: obj["default"],
			Help:    strOf(obj["help"]),
		})
	}
	return out
}

// bundleHelp renders manifest-derived help, mirroring flashcli_bundle.help_text.
func bundleHelp(m *manifest.Manifest, capability, variant string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Usage: flashcli %s <ref> [OPTIONS]\n", capability)
	if m.Description != "" {
		fmt.Fprintf(&b, "\n%s\n", m.Description)
	}
	if variants, ok := m.Raw["variants"].(map[string]any); ok && len(variants) > 0 {
		names := make([]string, 0, len(variants))
		for k := range variants {
			names = append(names, k)
		}
		sort.Strings(names)
		sel := variant
		if sel == "" {
			sel = "(none — add @<variant> to the ref)"
		}
		fmt.Fprintf(&b, "\nVariants: %s   selected: %s\n", strings.Join(names, ", "), sel)
	}
	fmt.Fprintf(&b, "\nHost options:\n")
	fmt.Fprintf(&b, "  --checkpoint PATH     Use local weights instead of the cache\n")
	fmt.Fprintf(&b, "  --quiet, -q           Suppress progress output\n")
	if capability == "serve" {
		fmt.Fprintf(&b, "  --port INT            HTTP port (default 8000)\n")
	} else {
		fmt.Fprintf(&b, "  --benchmark INT       Benchmark iterations\n")
		fmt.Fprintf(&b, "  --warmup INT          Warmup iterations\n")
	}
	opts := bundleOptionSpecs(m, capability, variant)
	if len(opts) > 0 {
		fmt.Fprintf(&b, "\nBundle options:\n")
		sort.Slice(opts, func(i, j int) bool { return opts[i].Flag < opts[j].Flag })
		for _, o := range opts {
			line := fmt.Sprintf("  --%s", o.Flag)
			if o.Type != "" && o.Type != "string" && o.Type != "boolean" {
				line += " " + strings.ToUpper(o.Type)
			}
			if o.Default != nil {
				line += fmt.Sprintf(" (default: %v)", o.Default)
			}
			if o.Help != "" {
				line += "  " + o.Help
			}
			b.WriteString(line + "\n")
		}
	}
	return b.String()
}

func strOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
