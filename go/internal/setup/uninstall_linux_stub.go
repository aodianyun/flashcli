//go:build !linux

package setup

import (
	"context"
	"fmt"
	"io"
)

func uninstallLinux(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("native uninstall is only supported on Linux")
}
