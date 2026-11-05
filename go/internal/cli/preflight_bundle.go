package cli

import (
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
)

// preflightBundle delegates to the shared host service.
func preflightBundle(m *manifest.Manifest, root, venvPython string, quiet, autoInstall bool) (string, error) {
	return host.PreflightBundle(m, root, venvPython, quiet, autoInstall)
}

// ensureBundleRuntime delegates to the shared host service.
func ensureBundleRuntime(m *manifest.Manifest, bundleRoot, version, variant string, quiet, noAutoInstall bool) (string, string, error) {
	return host.EnsureRuntime(m, bundleRoot, version, variant, quiet, noAutoInstall)
}
