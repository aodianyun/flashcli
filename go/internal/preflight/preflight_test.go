package preflight

import (
	"runtime"
	"strings"
	"testing"
)

func TestParseEnvKey(t *testing.T) {
	k, err := ParseEnvKey("sm89-cu124-linux-x86_64-py312")
	if err != nil {
		t.Fatal(err)
	}
	if k.SM != "89" || k.CudaTag != "124" || k.OSName != "linux" || k.Arch != "x86_64" || k.PythonMinor != "312" {
		t.Fatalf("unexpected: %+v", k)
	}
	if k.Name() != "sm89-cu124-linux-x86_64-py312" {
		t.Fatalf("roundtrip = %q", k.Name())
	}
	if _, err := ParseEnvKey("bad"); err == nil {
		t.Fatal("expected error")
	}
}

func TestVariantDirName(t *testing.T) {
	gpu := &GpuInfo{SM: "120", CudaTag: "130", OSName: "linux", Arch: "x86_64"}
	if got := VariantDirName(gpu, "310"); got != "sm120-cu130-linux-x86_64-py310" {
		t.Fatalf("VariantDirName = %q", got)
	}
}

func TestScoreEnvKeyMatch(t *testing.T) {
	host, _ := ParseEnvKey("sm89-cu124-linux-x86_64-py312")
	exact, _ := ParseEnvKey("sm89-cu124-linux-x86_64-py312")
	if ScoreEnvKeyMatch(exact, host) != 35 {
		t.Fatalf("exact score = %d", ScoreEnvKeyMatch(exact, host))
	}
	wrongPy, _ := ParseEnvKey("sm89-cu124-linux-x86_64-py310")
	if ScoreEnvKeyMatch(wrongPy, host) != 0 {
		t.Fatal("python mismatch should score 0")
	}
	sameFamily, _ := ParseEnvKey("sm89-cu128-linux-x86_64-py312")
	if s := ScoreEnvKeyMatch(sameFamily, host); s <= 20 {
		t.Fatalf("same-family score = %d", s)
	}
}

func TestResolveRuntimeEnvKey(t *testing.T) {
	runtimeMap := map[string]string{
		"sm89-cu124-linux-x86_64-py312":  "runtime/sm89-cu124-linux-x86_64-py312",
		"sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312",
	}
	if got := ResolveRuntimeEnvKey(runtimeMap, "sm89-cu124-linux-x86_64-py312"); got != "sm89-cu124-linux-x86_64-py312" {
		t.Fatalf("exact = %q", got)
	}
	// sm89 host with only a cu128 artifact of the same family.
	family := map[string]string{"sm89-cu128-linux-x86_64-py312": "runtime/x"}
	if got := ResolveRuntimeEnvKey(family, "sm89-cu124-linux-x86_64-py312"); got != "sm89-cu128-linux-x86_64-py312" {
		t.Fatalf("fuzzy = %q", got)
	}
	// python mismatch -> no match.
	if got := ResolveRuntimeEnvKey(map[string]string{"sm89-cu124-linux-x86_64-py310": "x"}, "sm89-cu124-linux-x86_64-py312"); got != "" {
		t.Fatalf("expected no match, got %q", got)
	}
}

func TestResolveRuntimeEnvKeyOverride(t *testing.T) {
	t.Setenv("FLASHCLI_RUNTIME_ENV_KEY", "sm120-cu130-linux-x86_64-py312")
	rm := map[string]string{
		"sm89-cu124-linux-x86_64-py312":  "a",
		"sm120-cu130-linux-x86_64-py312": "b",
	}
	if got := ResolveRuntimeEnvKey(rm, "sm89-cu124-linux-x86_64-py312"); got != "sm120-cu130-linux-x86_64-py312" {
		t.Fatalf("override = %q", got)
	}
}

func TestTorchIndexForTag(t *testing.T) {
	if TorchIndexForTag("130") != "cu128" || TorchIndexForTag("128") != "cu128" || TorchIndexForTag("124") != "cu124" {
		t.Fatal("torch index mapping wrong")
	}
}

func TestHostEnvKeyCPU(t *testing.T) {
	if got := HostEnvKey(nil, "312"); got != "cpu-"+strings.ToLower(runtime.GOOS)+"-"+normalizeArch(runtime.GOARCH)+"-py312" {
		t.Fatalf("CPU host key = %q", got)
	}
}

func TestResolveEnvironmentFallback(t *testing.T) {
	keys := []string{"nvidia-linux", "linux", "cpu-linux"}
	matches := map[string]map[string]any{
		"nvidia-linux": {"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia"},
		"linux":        {"os": "linux", "arch": "x86_64", "python_abi": "312"},
		"cpu-linux":    {"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "cpu"},
	}
	host, _ := ParseEnvKey("sm120-cu130-linux-x86_64-py312")
	got, err := ResolveEnvironment(keys, matches, host, "")
	if err != nil {
		t.Fatal(err)
	}
	if got != "nvidia-linux" {
		t.Fatalf("resolved = %q", got)
	}
	cpu, _ := ParseEnvKey("cpu-linux-x86_64-py312")
	got, err = ResolveEnvironment(keys, matches, cpu, "")
	if err != nil {
		t.Fatal(err)
	}
	if got != "cpu-linux" {
		t.Fatalf("CPU resolved = %q", got)
	}
}

func TestResolveEnvironmentTable(t *testing.T) {
	host := EnvKey{
		PlatformTail: "sm120-cu130", OSName: "linux", Arch: "x86_64",
		PythonMinor: "312", SM: "120", CudaTag: "130",
	}
	cases := []struct {
		name     string
		keys     []string
		matches  map[string]map[string]any
		host     EnvKey
		override string
		want     string
		wantErr  string
	}{
		{
			name: "exact key beats more specific fallback",
			keys: []string{"sm120-cu130-linux-x86_64-py312", "nvidia-extra"},
			matches: map[string]map[string]any{
				"nvidia-extra": {
					"os": "linux", "arch": "x86_64", "python_abi": "312",
					"vendor": "nvidia", "sm": "120", "cuda": "130",
				},
			},
			host: host,
			want: "sm120-cu130-linux-x86_64-py312",
		},
		{
			name: "lists and aliases match",
			keys: []string{"windows-arm"},
			matches: map[string]map[string]any{
				"windows-arm": {
					"os": []any{"windows", "win32"}, "arch": []any{"arm64"},
					"python_abi": "312", "vendor": []any{"nvidia", "amd"},
				},
			},
			host: EnvKey{PlatformTail: "sm120-cu130", OSName: "win32", Arch: "aarch64", PythonMinor: "312"},
			want: "windows-arm",
		},
		{
			name: "sm and cuda dimensions",
			keys: []string{"nvidia-sm120-cu130"},
			matches: map[string]map[string]any{
				"nvidia-sm120-cu130": {
					"os": "linux", "arch": "x86_64", "python_abi": "312",
					"vendor": "nvidia", "sm": "120", "cuda": []any{"130"},
				},
			},
			host: host,
			want: "nvidia-sm120-cu130",
		},
		{
			name: "py prefix normalization",
			keys: []string{"cpu"},
			matches: map[string]map[string]any{
				"cpu": {"os": "linux", "arch": "x86_64", "python_abi": "py312", "vendor": "cpu"},
			},
			host: EnvKey{PlatformTail: "cpu", OSName: "linux", Arch: "x86_64", PythonMinor: "312"},
			want: "cpu",
		},
		{
			name:     "invalid override",
			keys:     []string{"cpu"},
			override: "nope",
			host:     host,
			wantErr:  "not declared",
		},
		{
			name:     "override exact key",
			keys:     []string{"cpu", "nvidia"},
			override: "cpu",
			host:     host,
			want:     "cpu",
		},
		{
			name: "no match",
			keys: []string{"windows"},
			matches: map[string]map[string]any{
				"windows": {"os": "windows", "arch": "x86_64", "python_abi": "312"},
			},
			host:    host,
			wantErr: "no environment matches",
		},
		{
			name: "same specificity tie",
			keys: []string{"a", "b"},
			matches: map[string]map[string]any{
				"a": {"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": "nvidia"},
				"b": {"os": "linux", "arch": "x86_64", "python_abi": "312", "vendor": []any{"nvidia"}},
			},
			host:    host,
			wantErr: "ambiguous fallback",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := ResolveEnvironment(tc.keys, tc.matches, tc.host, tc.override)
			if tc.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("error = %v, want contains %q", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}
