package preflight

import "testing"

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
