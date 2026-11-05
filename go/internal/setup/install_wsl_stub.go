//go:build !windows

package setup

import (
	"context"
	"fmt"
	"io"
)

func installWSL(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("WSL installation is only supported on Windows")
}
