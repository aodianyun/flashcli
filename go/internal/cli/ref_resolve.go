package cli

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/version"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// ensureBundleRef resolves a local path or FlashHub ref to a local bundle root,
// syncing the tree from FlashHub on first use. Returns (root, version, variant).
func ensureBundleRef(refStr string, quiet, force bool) (string, string, string, error) {
	body, variant, err := ref.SplitVariant(refStr)
	if err != nil {
		return "", "", "", err
	}
	if !ref.IsFlashHub(refStr) {
		abs, err := filepath.Abs(body)
		if err != nil {
			return "", "", "", err
		}
		return abs, "local", variant, nil
	}

	p, err := ref.Parse(refStr)
	if err != nil {
		return "", "", "", err
	}
	repoURL, err := flashhub.RepoURL(flashhub.APIBase(), p.Namespace, p.Name, p.Version)
	if err != nil {
		return "", "", "", err
	}
	cacheKey := weights.CacheKey(p.Name, p.Version, variant)
	bundleDir := filepath.Join(paths.Bundles(), filepath.FromSlash(cacheKey))
	manifestPath := filepath.Join(bundleDir, flashhub.ManifestPath)

	if _, err := os.Stat(manifestPath); err == nil && !force {
		return bundleDir, p.Version, variant, nil
	}

	client := flashhub.NewClient()
	client.UserAgent = "flashcli/" + version.Version
	ctx := context.Background()

	manifestMap, err := client.DownloadManifest(ctx, repoURL, manifestPath, false, quiet)
	if err != nil {
		return "", "", "", err
	}
	m, err := manifest.LoadData(manifestMap, bundleDir)
	if err != nil {
		return "", "", "", err
	}
	if _, err := manifest.ResolveVariant(m, variant); err != nil {
		return "", "", "", err
	}
	envKey := resolveEnvKey(m)
	if envKey == "" {
		return "", "", "", fmt.Errorf("bundle %q has no runtime environment for this machine", m.Name)
	}
	if _, err := client.SyncBundle(ctx, repoURL, bundleDir, envKey, quiet); err != nil {
		return "", "", "", err
	}
	runtimeID := runtime.IDFromRepo(repoURL, p.Name)
	abi := m.PythonABIOrEmpty()
	if err := runtime.WriteMarker(runtimeID, map[string]any{
		"runtime_id":  runtimeID,
		"source":      "repo",
		"repo_url":    repoURL,
		"env_key":     envKey,
		"python_abi":  abi,
		"bundle_root": bundleDir,
		"preset":      m.Name,
	}); err != nil {
		return "", "", "", err
	}
	if err := flashhub.WriteMarker(bundleDir, map[string]any{
		"source":      "flashhub",
		"repo_url":    repoURL,
		"cache_key":   cacheKey,
		"env_key":     envKey,
		"bundle_root": bundleDir,
		"ref":         refStr,
		"runtime_id":  runtimeID,
	}); err != nil {
		return "", "", "", err
	}
	if !quiet {
		fmt.Fprintf(os.Stderr, "Synced %s -> %s (env %s)\n", refStr, bundleDir, envKey)
	}
	return bundleDir, p.Version, variant, nil
}

// writeLocalMarkers records runtime + preset markers for a local bundle.
func writeLocalMarkers(m *manifest.Manifest, root, variant string) (string, error) {
	runtimeID := runtime.IDFromPath(root, m.Name)
	envKey := resolveEnvKey(m)
	if err := runtime.WriteMarker(runtimeID, map[string]any{
		"runtime_id":  runtimeID,
		"source":      "local",
		"local_root":  root,
		"bundle_root": root,
		"env_key":     envKey,
		"preset":      m.Name,
	}); err != nil {
		return "", err
	}
	key := weights.CacheKey(m.Name, "local", variant)
	if err := runtime.WritePresetMarker(key, map[string]any{
		"source":      "local",
		"local_root":  root,
		"runtime_id":  runtimeID,
		"bundle_root": root,
		"env_key":     envKey,
		"ref":         m.Name,
	}); err != nil {
		return "", err
	}
	return runtimeID, nil
}

func resolveEnvKey(m *manifest.Manifest) string {
	if gpu := preflight.DetectGPU(); gpu != nil {
		if k := preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), preflight.VariantDirName(gpu, m.PythonABIOrEmpty())); k != "" {
			return k
		}
	}
	if k := strings.TrimSpace(os.Getenv("FLASHCLI_RUNTIME_ENV_KEY")); k != "" {
		return k
	}
	return m.SoleRuntimeKey()
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
			if _, err := manifest.ResolveVariant(m, variant); err != nil {
				return failed(cmd, err)
			}
			if _, _, err := ensureBundleRuntime(m, bundleRoot, ver, variant, quiet, noAutoInstall); err != nil {
				return failed(cmd, err)
			}
			checkpoint, _, err := weights.PrepareBundle(context.Background(), m, ver, variant, quiet)
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
