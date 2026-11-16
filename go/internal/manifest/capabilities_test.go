package manifest

import (
	"strings"
	"testing"
)

func TestServeCapabilitiesLegacyDefault(t *testing.T) {
	data := baseData(map[string]any{
		"serve": map[string]any{"module": "serve", "attr": "ServeEngine"},
	})
	m, err := LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	got := m.ServeCapabilities()
	if len(got) != 1 || got[0] != ServeCapOpenAIChat {
		t.Fatalf("legacy capabilities = %v", got)
	}
	if !m.EntryServe.CapabilitiesSet {
		// absent field must be distinguishable from explicit []
		if m.EntryServe.Capabilities != nil {
			t.Fatalf("absent capabilities parsed as %v", m.EntryServe.Capabilities)
		}
	}
}

func TestServeCapabilitiesExplicitAndEmpty(t *testing.T) {
	data := baseData(map[string]any{
		"serve": map[string]any{
			"module":       "serve",
			"attr":         "ServeEngine",
			"capabilities": []any{ServeCapOpenAIChat, ServeCapAnthropicMessages},
		},
	})
	m, err := LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	got := m.ServeCapabilities()
	if strings.Join(got, ",") != ServeCapOpenAIChat+","+ServeCapAnthropicMessages {
		t.Fatalf("capabilities = %v", got)
	}

	data = baseData(map[string]any{
		"serve": map[string]any{
			"module":       "serve",
			"attr":         "ServeEngine",
			"capabilities": []any{},
		},
	})
	m, err = LoadData(data, "/tmp")
	if err != nil {
		t.Fatal(err)
	}
	if got := m.ServeCapabilities(); len(got) != 0 {
		t.Fatalf("explicit empty capabilities = %v", got)
	}
}

func TestServeCapabilitiesValidation(t *testing.T) {
	cases := []struct {
		name string
		spec *EntrySpec
		want string
	}{
		{
			name: "unknown",
			spec: &EntrySpec{Kind: "python", Mode: "engine", CapabilitiesSet: true,
				Capabilities: []string{"bogus.protocol"}},
			want: "unknown capability",
		},
		{
			name: "duplicate",
			spec: &EntrySpec{Kind: "python", Mode: "engine", CapabilitiesSet: true,
				Capabilities: []string{ServeCapOpenAIChat, ServeCapOpenAIChat}},
			want: "duplicate capability",
		},
		{
			name: "script",
			spec: &EntrySpec{Kind: "python", Mode: "script", CapabilitiesSet: true,
				Capabilities: []string{ServeCapOpenAIChat}},
			want: "only valid for python engine serve",
		},
		{
			name: "invalid type",
			spec: &EntrySpec{Kind: "python", Mode: "engine", CapabilitiesSet: true,
				CapabilitiesInvalid: "must be an array"},
			want: "must be an array",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			joined := strings.Join(validateOneServeSpec("entry.serve", tc.spec), "\n")
			if !strings.Contains(joined, tc.want) {
				t.Fatalf("errors = %v, want %q", joined, tc.want)
			}
		})
	}
}

func TestServeCapabilitiesV4EnvironmentOverride(t *testing.T) {
	data := v4Fixture()
	envs := data["environments"].(map[string]any)
	linux := envs["linux"].(map[string]any)
	linux["entry"] = map[string]any{
		"serve": map[string]any{
			"kind":         "python",
			"module":       "serve",
			"attr":         "ServeEngine",
			"capabilities": []any{ServeCapOpenAIChat, ServeCapAnthropicMessages},
		},
	}
	m, err := LoadData(data, "/tmp/demo")
	if err != nil {
		t.Fatal(err)
	}
	env, err := m.ApplyEnv("linux")
	if err != nil {
		t.Fatal(err)
	}
	got := env.ServeCapabilities()
	if strings.Join(got, ",") != ServeCapOpenAIChat+","+ServeCapAnthropicMessages {
		t.Fatalf("env capabilities = %v", got)
	}
}
