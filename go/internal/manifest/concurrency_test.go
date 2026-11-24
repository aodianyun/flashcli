package manifest

import (
	"strings"
	"testing"
)

func TestServeConcurrencyDefaultAndExplicit(t *testing.T) {
	spec := entrySpecFromMap(map[string]any{
		"module": "serve",
		"attr":   "ServeEngine",
	}, "python", nil)
	if spec == nil {
		t.Fatal("spec is nil")
	}
	if spec.EffectiveServeConcurrency() != 1 {
		t.Fatalf("default concurrency = %d", spec.EffectiveServeConcurrency())
	}

	cases := []struct {
		value any
		want  int
	}{
		{2, 2},
		{float64(3), 3},
	}
	for _, tc := range cases {
		spec := entrySpecFromMap(map[string]any{
			"module":      "serve",
			"attr":        "ServeEngine",
			"concurrency": tc.value,
		}, "python", nil)
		if spec == nil || spec.ConcurrencyInvalid != "" {
			t.Fatalf("concurrency %v rejected: %+v", tc.value, spec)
		}
		if got := spec.EffectiveServeConcurrency(); got != tc.want {
			t.Fatalf("concurrency %v parsed as %d", tc.value, got)
		}
	}
}

func TestServeConcurrencyRejectsInvalidValues(t *testing.T) {
	for _, value := range []any{0, -1, 1.5, true, "2"} {
		spec := entrySpecFromMap(map[string]any{
			"module":      "serve",
			"attr":        "ServeEngine",
			"concurrency": value,
		}, "python", nil)
		if spec == nil || spec.ConcurrencyInvalid == "" {
			t.Fatalf("invalid concurrency %v accepted: %+v", value, spec)
		}
		if got := spec.EffectiveServeConcurrency(); got != 1 {
			t.Fatalf("invalid concurrency %v effective = %d", value, got)
		}
	}

	script := &EntrySpec{
		Kind: "python", Mode: "script", ConcurrencySet: true, Concurrency: 2,
	}
	joined := strings.Join(validateOneServeConcurrency("entry.serve", script), "\n")
	if !strings.Contains(joined, "only valid for python engine serve") {
		t.Fatalf("script concurrency accepted: %v", joined)
	}
}

func TestServeConcurrencyRequiresGatedCapability(t *testing.T) {
	cases := []struct {
		caps []string
		want bool
	}{
		{[]string{ServeCapAnthropicCountTokens}, true},
		{[]string{ServeCapAnthropicModels}, true},
		{[]string{}, true},
		{[]string{ServeCapOpenAIChat}, false},
		{[]string{ServeCapOpenAIEmbeddings}, false},
		{[]string{ServeCapAnthropicMessages}, false},
	}
	for _, tc := range cases {
		spec := &EntrySpec{
			Kind: "python", Mode: "engine", ConcurrencySet: true, Concurrency: 2,
			CapabilitiesSet: true, Capabilities: tc.caps,
		}
		joined := strings.Join(validateOneServeConcurrency("entry.serve", spec), "\n")
		if got := strings.Contains(joined, "gated"); got != tc.want {
			t.Fatalf("caps %v errors = %v, want gated=%v", tc.caps, joined, tc.want)
		}
	}
}
