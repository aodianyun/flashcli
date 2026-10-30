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
	seen := map[string]bool{}
	out := make([]string, 0)
	add := func(path string) {
		if path != "" && !seen[path] {
			seen[path] = true
			out = append(out, path)
		}
	}

	for _, m := range bundleMarkers() {
		if bundleRootUsable(strOf(m["bundle_root"])) {
			continue
		}
		key := strOf(m["cache_key"])
		if key == "" {
			continue
		}
		weightsKey := key
		if markerKey := strOf(m["weights_key"]); markerKey != "" {
			weightsKey = markerKey
		}
		add(filepath.Join(paths.Bundles(), filepath.FromSlash(key)))
		if !storeKeyUsedByOtherMarkers(weightsKey, key) {
			add(filepath.Join(paths.Models(), filepath.FromSlash(weightsKey)))
		}
		if rid := strOf(m["runtime_id"]); rid != "" {
			add(runtime.Dir(rid))
		}
	}

	entries, _ := os.ReadDir(paths.Runtimes())
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := runtime.Dir(e.Name())
		if seen[dir] {
			continue
		}
		marker := runtime.ReadMarker(e.Name())
		if len(marker) == 0 {
			add(dir)
			continue
		}
		root := strOf(marker["bundle_root"])
		if root == "" {
			root = strOf(marker["local_root"])
		}
		if !bundleRootUsable(root) {
			add(dir)
		}
	}
	return existingPaths(out)
}

func storeKeyUsedByOtherMarkers(weightsKey, currentBundleKey string) bool {
	for _, marker := range bundleMarkers() {
		if strOf(marker["cache_key"]) == currentBundleKey {
			continue
		}
		br := strOf(marker["bundle_root"])
		if br == "" {
			continue
		}
		man, err := manifest.Load(br)
		if err != nil || man.FormatVersion < 4 {
			continue
		}
		if weights.StoreKeyFor(man, "") == weightsKey {
			return true
		}
	}
	return false
}

func matchingMarkers(refArg string) []map[string]any {
	p, err := ref.Parse(refArg)
	if err != nil {
		return nil
	}
	targetKey := refCacheKey(p)
	var out []map[string]any
	for _, m := range bundleMarkers() {
		if strOf(m["ref"]) == refArg || strOf(m["cache_key"]) == refArg || strOf(m["cache_key"]) == targetKey {
			out = append(out, m)
		}
	}
	return out
}

func refRuntimePaths(refArg string) []string {
	var out []string
	if matches := matchingMarkers(refArg); len(matches) > 0 {
		for _, m := range matches {
			if rid := strOf(m["runtime_id"]); rid != "" {
				out = append(out, runtime.Dir(rid))
			}
		}
		if len(out) == 0 {
			if rid, ok := findRuntimeForRef(refArg); ok {
				out = append(out, runtime.Dir(rid))
			}
		}
		return existingPaths(out)
	}
	if rid, ok := findRuntimeForRef(refArg); ok {
		return []string{runtime.Dir(rid)}
	}
	return nil
}

func refAllPaths(refArg string) []string {
	if matches := matchingMarkers(refArg); len(matches) > 0 {
		var out []string
		foundRuntime := false
		for _, m := range matches {
			key := strOf(m["cache_key"])
			if key == "" {
				continue
			}
			weightsKey := key
			if markerKey := strOf(m["weights_key"]); markerKey != "" {
				weightsKey = markerKey
			} else if br := strOf(m["bundle_root"]); br != "" {
				if man, loadErr := manifest.Load(br); loadErr == nil && man.FormatVersion >= 4 {
					weightsKey = weights.StoreKeyFor(man, "")
				}
			}
			sharedWeights := storeKeyUsedByOtherMarkers(weightsKey, key)
			out = append(out, filepath.Join(paths.Bundles(), filepath.FromSlash(key)))
			if !sharedWeights {
				out = append(out, filepath.Join(paths.Models(), filepath.FromSlash(weightsKey)))
			}
			if rid := strOf(m["runtime_id"]); rid != "" {
				out = append(out, runtime.Dir(rid))
				foundRuntime = true
			}
		}
		if !foundRuntime {
			out = append(out, refRuntimePaths(refArg)...)
		}
		return existingPaths(out)
	}
	p, err := ref.Parse(refArg)
	if err != nil {
		return nil
	}
	key := refCacheKey(p)
	out := []string{
		filepath.Join(paths.Bundles(), filepath.FromSlash(key)),
		filepath.Join(paths.Models(), filepath.FromSlash(key)),
	}
	out = append(out, refRuntimePaths(refArg)...)
	return existingPaths(out)
}

func runtimePaths() []string {
	entries, _ := os.ReadDir(paths.Runtimes())
	out := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			out = append(out, runtime.Dir(e.Name()))
		}
	}
	return out
}

func allDataPaths() []string {
	return []string{paths.Runtimes(), paths.Models(), paths.Bundles()}
}

func refCacheKey(p ref.Parsed) string {
	version := p.Version
	if p.Local || version == "" {
		version = "local"
	}
	return weights.TreeKey(p.Name, version)
}

// findRuntimeForRef scans runtime markers for one whose preset/local_root match.
func findRuntimeForRef(refArg string) (string, bool) {
	p, err := ref.Parse(refArg)
	if err != nil {
		return "", false
	}
	root := paths.Runtimes()
	entries, err := os.ReadDir(root)
	if err == nil {
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
	}
	// Fallback: the bundle sync marker records the runtime id even when the
	// runtime marker is missing (older cache or an aborted run).
	if marker := runtime.ReadPresetMarker(refCacheKey(p)); marker != nil {
		if rid := strOf(marker["runtime_id"]); rid != "" {
			if _, err := os.Stat(runtime.Dir(rid)); err == nil {
				return rid, true
			}
		}
	}
	return "", false
}
