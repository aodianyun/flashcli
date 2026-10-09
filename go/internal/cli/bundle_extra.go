package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/weights"
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
	var full bool
	var flashhubCache bool
	cmd := &cobra.Command{
		Use:   "clean [ref]",
		Short: "Remove cached runtimes (default) or all local bundle data with --full",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			var refArg string
			if len(args) == 1 {
				refArg = args[0]
			}

			if full {
				var removed []string
				if refArg != "" {
					removed = cleanPresetCache(refArg, flashhubCache)
				} else {
					removed = cleanAllCached(flashhubCache)
				}
				if len(removed) == 0 {
					fmt.Fprintln(out, "No cached bundle data to remove.")
					return nil
				}
				for _, p := range removed {
					fmt.Fprintf(out, "Removed %s\n", p)
				}
				return nil
			}

			if all || refArg == "" {
				if _, err := os.Stat(paths.Runtimes()); err == nil {
					if err := os.RemoveAll(paths.Runtimes()); err != nil {
						return failed(cmd, err)
					}
					fmt.Fprintf(out, "Removed %s\n", paths.Runtimes())
				}
				return nil
			}

			if rid, ok := findRuntimeForRef(refArg); ok {
				dir := runtime.Dir(rid)
				if err := os.RemoveAll(dir); err != nil {
					return failed(cmd, err)
				}
				fmt.Fprintf(out, "Removed runtime %s\n", rid)
				return nil
			}
			fmt.Fprintf(out, "No cached runtime for preset %q\n", refArg)
			return nil
		},
	}
	cmd.Flags().BoolVar(&all, "all", false, "Remove all cached runtimes")
	cmd.Flags().BoolVar(&full, "full", false, "Also remove weights and bundle data")
	cmd.Flags().BoolVar(&flashhubCache, "flashhub-cache", false, "With --full: also remove FlashHub repo-index cache")
	return cmd
}

func rmtree(path string) (string, bool) {
	if _, err := os.Stat(path); err != nil {
		return "", false
	}
	if os.RemoveAll(path) != nil {
		return "", false
	}
	return path, true
}

func cleanAllCached(flashhubCache bool) []string {
	var removed []string
	for _, root := range []string{paths.Runtimes(), paths.Models(), paths.Bundles()} {
		if p, ok := rmtree(root); ok {
			removed = append(removed, p)
		}
	}
	if flashhubCache {
		if p, ok := rmtree(filepath.Join(paths.Cache(), "repo-index")); ok {
			removed = append(removed, p)
		}
	}
	return removed
}

func cleanPresetCache(refArg string, flashhubCache bool) []string {
	var removed []string
	p, err := ref.Parse(refArg)
	if err != nil {
		return removed
	}
	key := refCacheKey(p)
	marker := runtime.ReadPresetMarker(key)

	if br := strOf(marker["bundle_root"]); br != "" {
		if m, err := manifest.Load(br); err == nil {
			_, _, extras, _ := weights.ManifestSpecs(m, p.Variant)
			for k, spec := range extras {
				dest := weights.ExtraWeightDest("", br, k, spec)
				if spec.RelativeDir != "" {
					dest = filepath.Join(br, filepath.FromSlash(spec.RelativeDir))
				} else if spec.CacheName == "" {
					dest = filepath.Join(paths.Models(), k)
				}
				if d, ok := rmtree(dest); ok {
					removed = append(removed, d)
				}
			}
		}
	}
	if d, ok := rmtree(filepath.Join(paths.Models(), filepath.FromSlash(key))); ok {
		removed = append(removed, d)
	}
	if d, ok := rmtree(filepath.Join(paths.Bundles(), filepath.FromSlash(key))); ok {
		removed = append(removed, d)
	}
	if rid := strOf(marker["runtime_id"]); rid != "" {
		if d, ok := rmtree(runtime.Dir(rid)); ok {
			removed = append(removed, d)
		}
	}
	if flashhubCache {
		if repoURL := strOf(marker["repo_url"]); repoURL != "" {
			// Best-effort: drop the repo-index cache file (md5-keyed, same as client).
			cacheDir := filepath.Join(paths.Cache(), "repo-index")
			if entries, err := os.ReadDir(cacheDir); err == nil {
				for _, e := range entries {
					if d, ok := rmtree(filepath.Join(cacheDir, e.Name())); ok {
						removed = append(removed, d)
					}
				}
			}
		}
	}
	return removed
}

func refCacheKey(p ref.Parsed) string {
	version := p.Version
	if p.Local || version == "" {
		version = "local"
	}
	return weights.CacheKey(p.Name, version, p.Variant)
}

// findRuntimeForRef scans runtime markers for one whose preset/local_root match.
func findRuntimeForRef(refArg string) (string, bool) {
	p, err := ref.Parse(refArg)
	if err != nil {
		return "", false
	}
	root := paths.Runtimes()
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", false
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		blob, err := os.ReadFile(filepath.Join(root, e.Name(), ".runtime.json"))
		if err != nil {
			continue
		}
		var data map[string]any
		if json.Unmarshal(blob, &data) != nil {
			continue
		}
		if preset, _ := data["preset"].(string); preset == p.Name {
			return e.Name(), true
		}
		if localRoot, _ := data["local_root"].(string); localRoot != "" && p.Local &&
			strings.HasSuffix(filepath.Clean(localRoot), filepath.Clean(p.Name)) {
			return e.Name(), true
		}
	}
	return "", false
}
