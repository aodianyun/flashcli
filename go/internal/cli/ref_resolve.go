package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/ref"
)

// ensureBundleRef delegates to the shared host service.
func ensureBundleRef(refStr string, quiet, force bool) (string, string, string, error) {
	return host.EnsureBundle(refStr, quiet, force)
}

// writeLocalMarkers delegates to the shared host service.
func writeLocalMarkers(m *manifest.Manifest, root, variant string) (string, error) {
	return host.WriteLocalMarkers(m, root, variant)
}

// resolveEnvKey delegates to the shared host service.
func resolveEnvKey(m *manifest.Manifest) string {
	return host.ResolveEnvKey(m)
}

// applyEnv applies a v4 environment overlay for the current host.
func applyEnv(m *manifest.Manifest) (*manifest.Manifest, error) {
	return host.ApplyEnv(m)
}

func pullCmd() *cobra.Command {
	var quiet bool
	var noAutoInstall bool
	cmd := &cobra.Command{
		Use:   "pull <ref>",
		Short: "Download a bundle's weights into the flashcli cache",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			// Use the shared pull pipeline so the CLI, the desktop download and
			// app preparation always sync/prepare the same way.
			res, err := host.Pull(cmd.Context(), args[0], host.PullOptions{
				Quiet:         quiet,
				NoAutoInstall: noAutoInstall,
				VerifyWeights: true,
				Progress: func(ev host.PullEvent) {
					if quiet || ev.Message == "" {
						return
					}
					fmt.Fprintf(cmd.OutOrStdout(), "[%s] %s\n", ev.Phase, ev.Message)
				},
			})
			if err != nil {
				fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
				return ErrFailed
			}
			fmt.Fprintf(cmd.OutOrStdout(), "[ok] weights: %s\n", res.Checkpoint)
			return nil
		},
	}
	cmd.Flags().BoolVarP(&quiet, "quiet", "q", false, "Suppress progress output")
	cmd.Flags().BoolVar(&noAutoInstall, "no-auto-install", false, "Do not auto-install the Python stack")
	return cmd
}

func bundleSyncCmd() *cobra.Command {
	var quiet bool
	var force bool
	cmd := &cobra.Command{
		Use:   "sync <ref>",
		Short: "Pre-fetch a bundle tree from FlashHub (no weights)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !ref.IsFlashHub(args[0]) {
				fmt.Fprintln(cmd.OutOrStderr(), "Local bundle — runtime already on disk; bundle sync applies to FlashHub refs only.")
				return ErrFailed
			}
			bundleRoot, ver, variant, err := ensureBundleRef(args[0], quiet, force)
			if err != nil {
				return failed(cmd, err)
			}
			if m, lerr := manifest.Load(bundleRoot); lerr == nil {
				if _, _, rerr := ensureBundleRuntime(m, bundleRoot, ver, variant, quiet, false); rerr != nil {
					return failed(cmd, rerr)
				}
			}
			fmt.Fprintf(cmd.OutOrStdout(), "[ok] bundle: %s\n", bundleRoot)
			return nil
		},
	}
	cmd.Flags().BoolVarP(&quiet, "quiet", "q", false, "Suppress progress output")
	cmd.Flags().BoolVar(&force, "force", false, "Re-download manifest and artifacts")
	return cmd
}
