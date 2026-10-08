// Package ref parses flashcli preset references:
//
//	namespace/bundle:version[@variant]   FlashHub ref
//	bundles/<name>[@variant]             local dev path
//
// Mirrors flashcli_bundle/preset_ref.py.
package ref

import (
	"fmt"
	"regexp"
	"strings"
)

var shortRefRe = regexp.MustCompile(`^([^/]+)/([^:]+):([^@]+)$`)

// Parsed is a parsed preset reference.
type Parsed struct {
	Raw       string
	Namespace string
	Name      string
	Version   string
	Variant   string
	Local     bool
}

// SplitVariant splits "body@variant" into (body, variant). variant is "" when absent.
func SplitVariant(raw string) (string, string, error) {
	body := strings.TrimSpace(raw)
	if body == "" {
		return "", "", fmt.Errorf("Preset ref must not be empty")
	}
	if idx := strings.LastIndex(body, "@"); idx >= 0 {
		repoPart := strings.TrimSpace(body[:idx])
		variant := strings.TrimSpace(body[idx+1:])
		if variant == "" {
			return "", "", fmt.Errorf("Invalid preset ref %q: empty variant after '@'", raw)
		}
		return repoPart, variant, nil
	}
	return body, "", nil
}

// IsFlashHub reports whether raw looks like a FlashHub ref (not a local path).
func IsFlashHub(raw string) bool {
	body, _, err := SplitVariant(raw)
	if err != nil {
		return false
	}
	if strings.HasPrefix(body, "http://") || strings.HasPrefix(body, "https://") {
		return true
	}
	return shortRefRe.MatchString(body)
}

// Parse parses a preset ref. Local paths keep Local=true and Name set to the
// last path segment.
func Parse(raw string) (Parsed, error) {
	body, variant, err := SplitVariant(raw)
	if err != nil {
		return Parsed{}, err
	}
	p := Parsed{Raw: strings.TrimSpace(raw), Variant: variant}
	if strings.HasPrefix(body, "http://") || strings.HasPrefix(body, "https://") {
		trimmed := strings.TrimRight(body, "/")
		parts := strings.Split(trimmed, "/")
		last := parts[len(parts)-1]
		if idx := strings.Index(last, ":"); idx > 0 {
			p.Name = last[:idx]
			p.Version = last[idx+1:]
			if len(parts) >= 2 {
				p.Namespace = parts[len(parts)-2]
			}
			return p, nil
		}
		return Parsed{}, fmt.Errorf("Cannot parse bundle:version from URL path: %q", body)
	}
	if m := shortRefRe.FindStringSubmatch(body); m != nil {
		p.Namespace, p.Name, p.Version = m[1], m[2], m[3]
		return p, nil
	}
	p.Local = true
	segments := strings.Split(strings.TrimRight(body, "/"), "/")
	p.Name = segments[len(segments)-1]
	return p, nil
}
