package cli

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
)

func failed(cmd *cobra.Command, err error) error {
	fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
	if errors.Is(err, errs.Environment) {
		return &exitError{code: 2, err: err}
	}
	return ErrFailed
}

func bundleInstallCmd() *cobra.Command {
	var force bool
	var quiet bool
	cmd := &cobra.Command{
		Use:   "install <path>",
		Short: "Install a local bundle's inference dependencies (venv + pip)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			abs, err := filepath.Abs(args[0])
			if err != nil {
				return failed(cmd, err)
			}
			m, err := manifest.Load(abs)
			if err != nil {
				return failed(cmd, err)
			}
			if !m.NeedsPythonVenv() {
				fmt.Fprintln(cmd.OutOrStdout(), "No Python dependencies (native-only bundle); nothing to install.")
				return nil
			}
			runtimeID := runtime.IDFromPath(abs, m.Name)
			if _, err := venv.Ensure(context.Background(), runtimeID, m, venv.Options{
				Force: force, Quiet: quiet,
			}); err != nil {
				return failed(cmd, err)
			}
			fmt.Fprintln(cmd.OutOrStdout(), "Bundle inference dependencies installed.")
			return nil
		},
	}
	cmd.Flags().BoolVar(&force, "force", false, "Reinstall even if the venv fingerprint matches")
	cmd.Flags().BoolVarP(&quiet, "quiet", "q", false, "Suppress progress output")
	return cmd
}

func bundleCleanCmd() *cobra.Command {
	var all bool
	var orphans bool
	var yes bool
	cmd := &cobra.Command{
		Use:   "clean [ref]",
		Short: "Remove cached runtimes or all local bundle data with --all",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var refArg string
			if len(args) == 1 {
				refArg = args[0]
			}
			if orphans {
				if refArg != "" || all {
					return failed(cmd, errors.New("--orphans cannot be combined with a ref or --all"))
				}
				paths := orphanCachePaths()
				paths, err := confirmCleanup(cmd, paths, yes)
				if err != nil {
					return err
				}
				return removePaths(cmd, paths)
			}
			var paths []string
			switch {
			case all && refArg != "":
				paths = refAllPaths(refArg)
			case all:
				paths = allDataPaths()
			case refArg != "":
				paths = refRuntimePaths(refArg)
			default:
				paths = runtimePaths()
			}
			paths, err := confirmCleanup(cmd, paths, yes)
			if err != nil {
				return err
			}
			return removePaths(cmd, paths)
		},
	}
	cmd.Flags().BoolVar(&all, "all", false, "With a ref: also remove its bundle and weights; without a ref: remove all cached bundle data")
	cmd.Flags().BoolVar(&orphans, "orphans", false, "Remove stale bundle/model cache entries and runtimes with no valid bundle root")
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "Skip the Y/N confirmation (for scripts)")
	return cmd
}

// orphanCachePaths returns stale bundle/model entries whose preset marker
// bundle_root is gone, plus runtime dirs with no marker or no valid bundle root.
func orphanCachePaths() []string {
	return host.OrphanPaths()
}

func refRuntimePaths(refArg string) []string {
	return host.RefPaths(refArg, false)
}

func refAllPaths(refArg string) []string {
	return host.RefPaths(refArg, true)
}

func runtimePaths() []string {
	return host.RuntimePaths()
}

func allDataPaths() []string {
	return host.AllDataPaths()
}

func refCacheKey(p ref.Parsed) string {
	return host.RefCacheKey(p)
}
