// Package cli wires the flashcli command tree.
package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/doctor"
	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/native"
	"github.com/aodianyun/flashcli/go/internal/pythonprovision"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/version"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// ErrFailed signals a non-zero exit without cobra re-printing the message.
var ErrFailed = errors.New("command failed")

// New builds the root command tree.
func New() *cobra.Command {
	root := &cobra.Command{
		Use:           "flashcli",
		Short:         "FlashRT model bundle host (Go)",
		Version:       version.Version,
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.SetVersionTemplate("flashcli {{.Version}}\n")
	root.AddCommand(runCmd(), serveCmd(), pullCmd(), bundleCmd(), weightsCmd(), modelsCmd(), upgradeCmd(), doctorCmd(), versionCmd())
	return root
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print the flashcli-go version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), version.Version)
			return nil
		},
	}
}

func doctorCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Probe host capabilities for running bundles",
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			failed := false
			for _, c := range doctor.Run(version.Version) {
				mark := "[ok]"
				if !c.OK {
					mark = "[--]"
					failed = true
				}
				fmt.Fprintf(out, "%s %-12s %s\n", mark, c.Name, c.Detail)
			}
			if failed {
				return ErrFailed
			}
			return nil
		},
	}
}

type validateResult struct {
	OK     bool     `json:"ok"`
	Bundle string   `json:"bundle"`
	Errors []string `json:"errors"`
}

func bundleCmd() *cobra.Command {
	bundle := &cobra.Command{
		Use:   "bundle",
		Short: "Bundle utilities",
	}
	bundle.AddCommand(bundleValidateCmd(), bundleSyncCmd(), bundleInstallCmd(), bundleCleanCmd())
	return bundle
}

func bundleValidateCmd() *cobra.Command {
	var asJSON bool
	var executionOnly bool
	var skipABIProbe bool
	cmd := &cobra.Command{
		Use:   "validate [path]",
		Short: "Validate a local bundle manifest",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			path := "."
			if len(args) == 1 {
				path = args[0]
			}
			var errs []string
			m, err := manifest.Load(path)
			if err != nil {
				errs = []string{err.Error()}
			} else if executionOnly {
				errs = manifest.ValidateExecution(m)
			} else {
				errs = manifest.Validate(m)
				if !skipABIProbe {
					errs = append(errs, native.ProbeRuntimeABI(m.Root, m.RuntimeMap(), func(minor string) (string, bool) {
						if p, perr := venv.ResolveBasePython(minor); perr == nil {
							return p, true
						}
						if p, ok, ierr := pythonprovision.Ensure(context.Background(), minor, pythonprovision.Enabled(), true); ierr == nil && ok {
							return p, true
						}
						return "", false
					})...)
				}
			}
			if errs == nil {
				errs = []string{}
			}
			ok := len(errs) == 0
			if asJSON {
				blob, _ := json.MarshalIndent(validateResult{OK: ok, Bundle: path, Errors: errs}, "", "  ")
				fmt.Fprintln(cmd.OutOrStdout(), string(blob))
			} else if ok {
				fmt.Fprintf(cmd.OutOrStdout(), "[ok] bundle: %s\n", path)
			} else {
				for _, e := range errs {
					fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", e)
				}
			}
			if !ok {
				return ErrFailed
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Emit machine-readable JSON")
	cmd.Flags().BoolVar(&executionOnly, "execution-only", false, "Validate only the execution ABI (docs/bundle_execution_abi.md)")
	cmd.Flags().BoolVar(&skipABIProbe, "skip-abi-probe", false, "Skip load-testing each runtime/*.so with its tagged Python")
	return cmd
}

func weightsCmd() *cobra.Command {
	weightsRoot := &cobra.Command{
		Use:   "weights",
		Short: "Weight cache utilities",
	}
	weightsRoot.AddCommand(weightsPullCmd())
	return weightsRoot
}

func weightsPullCmd() *cobra.Command {
	var variant string
	var ver string
	var quiet bool
	cmd := &cobra.Command{
		Use:   "pull <bundle-path>",
		Short: "Download a local bundle's weights into the flashcli cache",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			m, err := manifest.Load(args[0])
			if err != nil {
				fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
				return ErrFailed
			}
			checkpoint, err := weights.DownloadBundle(context.Background(), m, ver, variant, quiet)
			if err != nil {
				fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
				return ErrFailed
			}
			fmt.Fprintf(cmd.OutOrStdout(), "[ok] weights: %s\n", checkpoint)
			return nil
		},
	}
	cmd.Flags().StringVar(&variant, "variant", "", "Bundle variant (required for multi-variant manifests)")
	cmd.Flags().StringVar(&ver, "version", "local", "Version for the cache key")
	cmd.Flags().BoolVar(&quiet, "quiet", false, "Suppress progress output")
	return cmd
}

// Main runs the CLI and returns a process exit code.
func Main(args []string) int {
	root := New()
	root.SetArgs(normalizeVersionAlias(args))
	if err := root.Execute(); err != nil {
		var ee *exitError
		if errors.As(err, &ee) {
			return ee.code
		}
		if errors.Is(err, ErrFailed) {
			return 1
		}
		fmt.Fprintln(os.Stderr, "error:", err)
		if errors.Is(err, errs.Environment) {
			return 2
		}
		return 1
	}
	return 0
}

// normalizeVersionAlias maps the Python-compatible -V alias to --version.
func normalizeVersionAlias(args []string) []string {
	if len(args) > 0 && args[0] == "-V" {
		cp := append([]string{}, args...)
		cp[0] = "--version"
		return cp
	}
	return args
}

// exitError carries a specific process exit code.
type exitError struct {
	code int
	err  error
}

func (e *exitError) Error() string { return e.err.Error() }
func (e *exitError) Unwrap() error { return e.err }
