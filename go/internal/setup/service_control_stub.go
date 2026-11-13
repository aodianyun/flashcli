//go:build !windows && !linux

package setup

import (
	"context"
	"fmt"
	"io"
)

func stopService(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("service control is only supported on Linux and Windows")
}

func disableAutostart(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("service control is only supported on Linux and Windows")
}

func enableAutostart(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("service control is only supported on Linux and Windows")
}

func startService(context.Context, Env, Options, io.Writer) error {
	return fmt.Errorf("service control is only supported on Linux and Windows")
}
