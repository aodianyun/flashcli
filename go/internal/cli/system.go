package cli

import (
	"context"
	"fmt"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/progress"
	"github.com/aodianyun/flashcli/go/internal/system"
)

func ensureSystemRequirements(m *manifest.Manifest, python string, quiet bool) error {
	reqs := m.SystemRequires()
	if len(reqs) == 0 {
		return nil
	}
	ctx := context.Background()
	statuses, err := system.Check(ctx, reqs, python)
	if err != nil {
		return err
	}
	missing := system.Missing(statuses)
	if len(missing) == 0 {
		return nil
	}
	abi := m.PythonABIOrEmpty()
	details := make([]string, 0, len(missing))
	for _, cap := range missing {
		hint := system.PackageHint(cap, abi)
		details = append(details, fmt.Sprintf("%s (install: %s)", cap, hint))
		progress.Note("missing system capability: %s (install: %s)", cap, hint)
	}
	if !system.AutoInstallEnabled() {
		return fmt.Errorf("missing system capabilities: %s; install them and retry", strings.Join(details, ", "))
	}
	if !quiet {
		progress.Note("installing system capabilities: %s", strings.Join(capStrings(missing), ", "))
	}
	if err := system.Install(ctx, missing, abi, quiet); err != nil {
		return fmt.Errorf("system capability installation failed: %w", err)
	}
	statuses, err = system.Check(ctx, reqs, python)
	if err != nil {
		return err
	}
	missing = system.Missing(statuses)
	if len(missing) > 0 {
		return fmt.Errorf("system capabilities still missing after install: %s", strings.Join(capStrings(missing), ", "))
	}
	return nil
}

func capStrings(caps []system.Capability) []string {
	out := make([]string, len(caps))
	for i, c := range caps {
		out[i] = string(c)
	}
	return out
}
