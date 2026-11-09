package setup

import (
	"context"
	"fmt"
	"io"
)

// uninstall removes the flashserver service/config/binary but keeps model and
// weight caches under FLASHCLI_HOME.
func uninstall(ctx context.Context, env Env, opts Options, out io.Writer) error {
	switch EffectiveBackend(env, opts.Backend) {
	case "native":
		return uninstallLinux(ctx, env, opts, out)
	case "wsl":
		return uninstallWSL(ctx, env, opts, out)
	default:
		return fmt.Errorf("unknown backend %q", EffectiveBackend(env, opts.Backend))
	}
}
