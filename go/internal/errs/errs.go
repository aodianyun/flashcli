// Package errs carries cross-cutting error classification (exit codes).
package errs

import (
	"errors"
	"fmt"
)

// Environment marks bundle-environment failures (exit code 2), mirroring
// flashcli.bundle.preflight.BundleEnvironmentError.exit_code.
var Environment = errors.New("bundle environment error")

// EnvWrapf wraps an error as an Environment error with a formatted message.
func EnvWrapf(format string, args ...any) error {
	return fmt.Errorf("%w: %s", Environment, fmt.Sprintf(format, args...))
}

// Envf returns an Environment error with a formatted message.
func Envf(format string, args ...any) error {
	return fmt.Errorf("%w: %s", Environment, fmt.Sprintf(format, args...))
}
