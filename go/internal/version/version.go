// Package version exposes the flashcli-go build identity.
//
// The value is injected at build time from the single source of truth (root
// pyproject.toml [project].version) via:
//
//	go build -ldflags "-X github.com/aodianyun/flashcli/go/internal/version.Version=$(...)"
package version

// Version is the flashcli-go build version ("dev" for local builds).
var Version = "dev"

// Protocol mirrors flashcli_bundle.version for cross-checks.
const (
	ProtocolVersion     = 1
	RuntimeABIVersion   = 1
	ExecProtocolVersion = 1
)
