// Package paths resolves the flashcli on-disk layout shared by the host.
//
// Mirrors flashcli_bundle/paths.py.
package paths

import (
	"os"
	"path/filepath"
)

// Home returns FLASHCLI_HOME (default ~/.flashcli).
func Home() string {
	if v := os.Getenv("FLASHCLI_HOME"); v != "" {
		return expandHome(v)
	}
	return filepath.Join(userHome(), ".flashcli")
}

// Models returns FLASHCLI_MODELS_DIR (default $FLASHCLI_HOME/models).
func Models() string {
	if v := os.Getenv("FLASHCLI_MODELS_DIR"); v != "" {
		return expandHome(v)
	}
	return filepath.Join(Home(), "models")
}

// Bundles returns FLASHCLI_BUNDLES_DIR (default $FLASHCLI_HOME/bundles).
func Bundles() string {
	if v := os.Getenv("FLASHCLI_BUNDLES_DIR"); v != "" {
		return expandHome(v)
	}
	return filepath.Join(Home(), "bundles")
}

// Runtimes returns FLASHCLI_RUNTIMES_DIR (default $FLASHCLI_HOME/runtimes).
func Runtimes() string {
	if v := os.Getenv("FLASHCLI_RUNTIMES_DIR"); v != "" {
		return expandHome(v)
	}
	return filepath.Join(Home(), "runtimes")
}

// Cache returns $FLASHCLI_HOME/cache/downloads.
func Cache() string {
	return filepath.Join(Home(), "cache", "downloads")
}

func userHome() string {
	if h, err := os.UserHomeDir(); err == nil && h != "" {
		return h
	}
	return "."
}

func expandHome(p string) string {
	if p == "~" || (len(p) > 1 && p[0] == '~' && (p[1] == '/' || p[1] == filepath.Separator)) {
		return filepath.Join(userHome(), p[2:])
	}
	return p
}
