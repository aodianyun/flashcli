package setup

import (
	"strings"
	"testing"
)

func stepNames(steps []Step) string {
	var names []string
	for _, step := range steps {
		names = append(names, step.Name)
	}
	return strings.Join(names, ",")
}

func TestPlanLinuxNative(t *testing.T) {
	steps, err := Plan(Env{OS: "linux", Arch: "amd64"}, "auto")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(stepNames(steps), "install") || !strings.Contains(stepNames(steps), "health") {
		t.Fatalf("unexpected plan: %s", stepNames(steps))
	}
}

func TestPlanWindowsWSL(t *testing.T) {
	steps, err := Plan(Env{OS: "windows", Arch: "amd64"}, "auto")
	if err != nil {
		t.Fatal(err)
	}
	names := stepNames(steps)
	for _, want := range []string{"check-wsl2", "ensure-distro", "install", "startup", "health"} {
		if !strings.Contains(names, want) {
			t.Fatalf("missing %s in %s", want, names)
		}
	}
}

func TestPlanUnsupportedOS(t *testing.T) {
	if _, err := Plan(Env{OS: "darwin", Arch: "arm64"}, "auto"); err == nil {
		t.Fatal("darwin is not supported in the first phase")
	}
}

func TestPlanWindowsNativeUnavailable(t *testing.T) {
	if _, err := Plan(Env{OS: "windows", Arch: "amd64"}, "native"); err == nil {
		t.Fatal("windows native must be unavailable in this build")
	}
}

func TestPlanRejectsWSLOnLinux(t *testing.T) {
	if _, err := Plan(Env{OS: "linux", Arch: "amd64"}, "wsl"); err == nil {
		t.Fatal("wsl backend must be rejected on Linux")
	}
}
