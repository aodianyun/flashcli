//go:build !windows

package setup

import (
	"context"
	"fmt"
	"io"
)

func uninstallWSL(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("WSL uninstall is only supported on Windows")
}
