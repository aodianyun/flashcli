package manifest

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/preflight"
)

// EnvironmentMatches returns the optional fallback match blocks keyed by
// environment.
func (m *Manifest) EnvironmentMatches() map[string]map[string]any {
	out := map[string]map[string]any{}
	for key, block := range m.Environments {
		if match, ok := block["match"].(map[string]any); ok {
			out[key] = match
		}
	}
	return out
}

// ResolveEnvKey resolves an exact v4 environment first, then explicit fallback
// match blocks. v3 keeps the legacy resolver.
func (m *Manifest) ResolveEnvKey(hostKey string) (string, error) {
	if m.FormatVersion < FormatVersionV4 {
		key := preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), hostKey)
		if key == "" {
			return "", fmt.Errorf("bundle %q has no runtime environment for host %q", m.Name, hostKey)
		}
		return key, nil
	}
	host, err := preflight.ParseEnvKey(hostKey)
	if err != nil {
		return "", err
	}
	return preflight.ResolveEnvironment(m.EnvironmentKeys(), m.EnvironmentMatches(), host, os.Getenv("FLASHCLI_RUNTIME_ENV_KEY"))
}

func validateEnvironmentFallbacks(envs map[string]map[string]any) error {
	type entry struct {
		key    string
		match  map[string]any
		weight int
	}
	var fallbacks []entry
	allowed := map[string]bool{
		"os": true, "arch": true, "python_abi": true,
		"vendor": true, "sm": true, "cuda": true,
	}
	for key, block := range envs {
		raw, ok := block["match"]
		if !ok {
			continue
		}
		match, ok := raw.(map[string]any)
		if !ok {
			return fmt.Errorf("environments.%s.match must be an object", key)
		}
		if len(match) == 0 {
			return fmt.Errorf("environments.%s.match must not be empty", key)
		}
		for dim, value := range match {
			if !allowed[strings.ToLower(strings.TrimSpace(dim))] {
				return fmt.Errorf("environments.%s.match has unsupported dimension %q", key, dim)
			}
			if !validMatchValue(value) {
				return fmt.Errorf("environments.%s.match.%s must be a string or string list", key, dim)
			}
		}
		for _, required := range []string{"os", "arch", "python_abi"} {
			if _, ok := match[required]; !ok {
				return fmt.Errorf("environments.%s.match requires %s", key, required)
			}
		}
		fallbacks = append(fallbacks, entry{key: key, match: match, weight: len(match)})
	}
	sort.Slice(fallbacks, func(i, j int) bool { return fallbacks[i].key < fallbacks[j].key })
	for i := 0; i < len(fallbacks); i++ {
		for j := i + 1; j < len(fallbacks); j++ {
			a, b := fallbacks[i], fallbacks[j]
			if a.weight != b.weight {
				continue
			}
			if matchOverlap(a.match, b.match) {
				return fmt.Errorf(
					"ambiguous fallback environments %q and %q: same specificity and overlapping match dimensions",
					a.key, b.key,
				)
			}
		}
	}
	return nil
}

func validMatchValue(value any) bool {
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v) != ""
	case []any:
		if len(v) == 0 {
			return false
		}
		for _, item := range v {
			s, ok := item.(string)
			if !ok || strings.TrimSpace(s) == "" {
				return false
			}
		}
		return true
	case []string:
		return len(v) > 0
	default:
		return false
	}
}

func matchOverlap(a, b map[string]any) bool {
	for dim, av := range a {
		bv, ok := b[dim]
		if !ok {
			continue
		}
		if !valuesOverlap(dim, av, bv) {
			return false
		}
	}
	return true
}

func valuesOverlap(dim string, a, b any) bool {
	as := matchValues(a)
	bs := matchValues(b)
	if len(as) == 0 || len(bs) == 0 {
		return true
	}
	for _, av := range as {
		for _, bv := range bs {
			if matchValueEqual(dim, av, bv) {
				return true
			}
		}
	}
	return false
}

func matchValues(v any) []string {
	switch x := v.(type) {
	case string:
		return []string{strings.ToLower(strings.TrimSpace(x))}
	case []any:
		out := make([]string, 0, len(x))
		for _, item := range x {
			if s, ok := item.(string); ok {
				out = append(out, strings.ToLower(strings.TrimSpace(s)))
			}
		}
		return out
	case []string:
		out := make([]string, 0, len(x))
		for _, s := range x {
			out = append(out, strings.ToLower(strings.TrimSpace(s)))
		}
		return out
	default:
		return nil
	}
}

func matchValueEqual(dim, a, b string) bool {
	if dim == "python_abi" {
		a = strings.TrimPrefix(a, "py")
		b = strings.TrimPrefix(b, "py")
	}
	if dim == "os" {
		if (a == "windows" || a == "win32") && (b == "windows" || b == "win32") {
			return true
		}
	}
	if dim == "arch" {
		if (a == "aarch64" || a == "arm64") && (b == "aarch64" || b == "arm64") {
			return true
		}
	}
	return a == b
}
