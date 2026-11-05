package cli

import (
	"context"
	"fmt"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/hostabi"
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

func ensureELFInspector(quiet, autoInstall bool) error {
	if envBool("FLASHCLI_SKIP_NATIVE_HOST_ABI") || hostabi.InspectorAvailable() {
		return nil
	}
	hint := "binutils"
	if !autoInstall || !system.AutoInstallEnabled() {
		return fmt.Errorf("missing readelf/objdump for native host ABI check; install %s and retry", hint)
	}
	if !quiet {
		progress.Note("installing system capability: ELF inspector (%s)", hint)
	}
	if err := system.InstallBinutils(context.Background(), quiet); err != nil {
		return fmt.Errorf("ELF inspector installation failed: %w", err)
	}
	if !hostabi.InspectorAvailable() {
		return fmt.Errorf("readelf/objdump still missing after installing %s", hint)
	}
	return nil
}
