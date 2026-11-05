// Package system defines the bundle system-capability contract and resolves
// those capabilities to distro packages.
package system

import (
	"fmt"
	"sort"
	"strings"
)

// Capability is a host capability a bundle may require.
type Capability string

const (
	CCompiler     Capability = "c-compiler"
	CXXCompiler   Capability = "cxx-compiler"
	PythonHeaders Capability = "python-headers"
)

var allowed = map[Capability]bool{
	CCompiler:     true,
	CXXCompiler:   true,
	PythonHeaders: true,
}

// Parse validates and normalizes a manifest capability list.
func Parse(values []string) ([]Capability, error) {
	out := make([]Capability, 0, len(values))
	seen := map[Capability]bool{}
	for _, raw := range values {
		name := Capability(strings.ToLower(strings.TrimSpace(raw)))
		if name == "" {
			return nil, fmt.Errorf("system.requires must not contain an empty capability")
		}
		if !allowed[name] {
			return nil, fmt.Errorf("unsupported system capability %q", raw)
		}
		if seen[name] {
			return nil, fmt.Errorf("duplicate system capability %q", raw)
		}
		seen[name] = true
		out = append(out, name)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out, nil
}

// Validate checks a manifest capability list.
func Validate(values []string) error {
	_, err := Parse(values)
	return err
}

// Allowed reports whether name is in the first-phase capability whitelist.
func Allowed(name Capability) bool { return allowed[name] }
