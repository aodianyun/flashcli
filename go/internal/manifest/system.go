package manifest

import "github.com/aodianyun/flashcli/go/internal/system"

// SystemRequires returns the bundle's v4 system capability requirements.
func (m *Manifest) SystemRequires() []string {
	if m == nil {
		return nil
	}
	block, _ := m.Raw["system"].(map[string]any)
	raw, _ := block["requires"].([]any)
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func validateSystemRequirements(m *Manifest) []string {
	if m.FormatVersion < FormatVersionV4 {
		return nil
	}
	block, ok := m.Raw["system"]
	if !ok {
		return nil
	}
	obj, ok := block.(map[string]any)
	if !ok {
		return []string{"system must be an object"}
	}
	raw, ok := obj["requires"]
	if !ok {
		return []string{"system.requires is required when system is present"}
	}
	list, ok := raw.([]any)
	if !ok {
		return []string{"system.requires must be an array of strings"}
	}
	values := make([]string, 0, len(list))
	for _, item := range list {
		s, ok := item.(string)
		if !ok {
			return []string{"system.requires must contain only strings"}
		}
		values = append(values, s)
	}
	if err := system.Validate(values); err != nil {
		return []string{err.Error()}
	}
	if m.PythonABIOrEmpty() == "" && containsCapability(values, string(system.PythonHeaders)) {
		return []string{"system.requires python-headers requires python_abi"}
	}
	return nil
}

func containsCapability(values []string, want string) bool {
	for _, v := range values {
		if v == want {
			return true
		}
	}
	return false
}
