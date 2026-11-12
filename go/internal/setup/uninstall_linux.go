//go:build linux

package setup

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func uninstallLinux(ctx context.Context, env Env, opts Options, out io.Writer) error {
	i := installer{env: env, opts: opts, out: out}
	if os.Geteuid() != 0 {
		return fmt.Errorf("uninstall requires root; rerun with sudo")
	}
	_ = i.run(ctx, "systemctl", "disable", "--now", opts.ServiceName)
	_ = os.Remove(filepath.Join("/etc/systemd/system", opts.ServiceName+".service"))
	_ = i.run(ctx, "systemctl", "daemon-reload")
	_ = os.Remove(opts.ConfigPath)
	_ = os.Remove(filepath.Join(opts.Prefix, "bin", "flashserver"))
	if opts.RemoveCLI {
		_ = os.Remove(filepath.Join(opts.Prefix, "bin", "flashcli"))
	}
	if opts.PurgeModels && strings.HasPrefix(opts.Home, "/") && opts.Home != "/" {
		i.printf("remove model caches %s\n", opts.Home)
		_ = os.RemoveAll(opts.Home)
		_ = os.RemoveAll("/usr/local/share/flashcli")
	}
	if opts.PurgeModels {
		i.printf("removed flashserver service/config/binary and model caches\n")
	} else {
		i.printf("removed flashserver service/config/binary; kept %s and model caches\n", opts.Home)
	}
	return nil
}
