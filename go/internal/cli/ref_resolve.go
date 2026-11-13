package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/weights"
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
			bundleRoot, ver, variant, err := ensureBundleRef(args[0], quiet, false)
			if err != nil {
				fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
				return ErrFailed
			}
			m, err := manifest.Load(bundleRoot)
			if err != nil {
				return failed(cmd, err)
			}
			m, err = applyEnv(m)
			if err != nil {
				return failed(cmd, err)
			}
			if _, err := manifest.ResolveVariant(m, variant); err != nil {
				return failed(cmd, err)
			}
			if _, _, err := ensureBundleRuntime(m, bundleRoot, ver, variant, quiet, noAutoInstall); err != nil {
				return failed(cmd, err)
			}
			checkpoint, _, err := weights.PrepareBundle(context.Background(), m, ver, variant, quiet, true)
			if err != nil {
				fmt.Fprintf(cmd.OutOrStderr(), "[!] %s\n", err)
				return ErrFailed
			}
			fmt.Fprintf(cmd.OutOrStdout(), "[ok] weights: %s\n", checkpoint)
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
