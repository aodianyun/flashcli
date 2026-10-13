package cli

import "testing"

func TestPeelHostFlags(t *testing.T) {
	hf := peelHostFlags([]string{"bundles/x", "--checkpoint", "/ck", "--quiet", "--prompt", "hi"})
	if hf.Ref != "bundles/x" || hf.Checkpoint != "/ck" || !hf.Quiet {
		t.Fatalf("unexpected: %+v", hf)
	}
	hf = peelHostFlags([]string{"ref", "--mtp-checkpoint=/m", "--no-auto-install", "-h"})
	if hf.MTPCheckpoint != "/m" || !hf.NoAutoInstall || !hf.WantsHelp {
		t.Fatalf("unexpected: %+v", hf)
	}
	if hf := peelHostFlags([]string{"--help"}); hf.Ref != "" || !hf.WantsHelp {
		t.Fatalf("help-only: %+v", hf)
	}
}

func TestParseFlagsSkipsHostFlags(t *testing.T) {
	got := parseFlags([]string{"bundles/x", "--checkpoint", "/ck", "--prompt", "hi", "--use-fp8"})
	if got["prompt"] != "hi" {
		t.Fatalf("prompt = %v", got["prompt"])
	}
	if got["use-fp8"] != true {
		t.Fatalf("use-fp8 = %v", got["use-fp8"])
	}
	if _, ok := got["checkpoint"]; ok {
		t.Fatalf("checkpoint should be skipped: %v", got)
	}
}
