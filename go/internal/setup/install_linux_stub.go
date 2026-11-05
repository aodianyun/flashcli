//go:build !linux

package setup

import (
	"context"
	"fmt"
	"io"
)

func installLinux(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("native installation is only supported on Linux")
}
