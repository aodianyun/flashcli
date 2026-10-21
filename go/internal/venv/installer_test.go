package venv

import (
	"context"
	"strings"
	"testing"
)

func TestInstallArgsSelectsBackend(t *testing.T) {
	t.Setenv("FLASHCLI_VENV_BACKEND", "pip")
	r := &captureRunner{}
	if err := InstallArgs(context.Background(), r, "/v/bin/python", []string{"somepkg"}, true); err != nil {
		t.Fatal(err)
	}
	if len(r.calls) != 1 || !strings.Contains(strings.Join(r.calls[0], " "), "-m pip install") {
		t.Fatalf("pip backend argv: %v", r.calls)
	}

	uvBin := stubUV(t, "0.9.3")
	t.Setenv("FLASHCLI_VENV_BACKEND", "uv")
	t.Setenv("FLASHCLI_UV_BIN", uvBin)
	r2 := &captureRunner{}
	if err := InstallArgs(context.Background(), r2, "/v/bin/python", []string{"somepkg"}, true); err != nil {
		t.Fatal(err)
	}
	if len(r2.calls) != 1 {
		t.Fatalf("uv backend calls: %v", r2.calls)
	}
	got := r2.calls[0]
	if len(got) < 5 || got[0] != uvBin || got[1] != "pip" || got[2] != "install" || got[3] != "--python" || got[4] != "/v/bin/python" {
		t.Fatalf("uv backend argv: %v", got)
	}
}
