package cli

import (
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
)

func ensureSystemRequirements(m *manifest.Manifest, python string, quiet bool) error {
	return host.EnsureSystemRequirements(m, python, quiet)
}
