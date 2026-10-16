package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/version"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

func modelsCmd() *cobra.Command {
	root := &cobra.Command{
		Use:   "models",
		Short: "Model/bundle cache utilities",
	}
	root.AddCommand(modelsEnvsCmd(), modelsListCmd(), modelsShowCmd())
	return root
}

// bundleMarkers lists preset markers under Bundles().
func bundleMarkers() []map[string]any {
	root := paths.Bundles()
	var out []map[string]any
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || d.Name() != flashhub.MarkerName {
			return nil
		}
		blob, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		var data map[string]any
		if json.Unmarshal(blob, &data) != nil {
			return nil
		}
		rel, relErr := filepath.Rel(root, filepath.Dir(path))
		if relErr == nil {
			data["cache_key"] = filepath.ToSlash(rel)
		}
		out = append(out, data)
		return nil
	})
	return out
}

func weightsCachedFor(p ref.Parsed, refStr string) bool {
	ver := p.Version
	if p.Local || ver == "" {
		ver = "local"
	}
	key := weights.TreeKey(p.Name, ver)
	rel := "checkpoint"
	if m, err := loadManifestForRef(refStr, p); err == nil {
		key = weights.CacheKeyFor(m, ver)
		if _, r, _, err := weights.ManifestSpecs(m, p.Variant); err == nil && r != "" {
			rel = r
		}
	}
	dir := filepath.Join(paths.Models(), filepath.FromSlash(key), filepath.FromSlash(rel))
	if cp, ok := weights.ReadMarker(dir); ok {
		if info, err := os.Stat(cp); err == nil && info.IsDir() {
			return true
		}
	}
	return false
}

func modelsListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List locally synced bundles",
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			markers := bundleMarkers()
			if len(markers) == 0 {
				fmt.Fprintln(out, "No cached presets. Run flashcli run <ref> or flashcli bundle sync <ref>.")
				return nil
			}
			sort.Slice(markers, func(i, j int) bool {
				return fmt.Sprint(markers[i]["cache_key"]) < fmt.Sprint(markers[j]["cache_key"])
			})
			for _, m := range markers {
				cacheKey := fmt.Sprint(m["cache_key"])
				refName := strOf(m["ref"])
				if refName == "" {
					refName = cacheKey
				}
				variant := ""
				if v := strOf(m["variant"]); v != "" {
					variant = ", variant=" + v
				}
				bundleState := "bundle:missing"
				if br := strOf(m["bundle_root"]); br != "" {
					bundleState = fmt.Sprintf("bundle:cached (%s)", strOf(m["env_key"]))
				}
				weightsState := "weights:missing"
				if weightsCachedFromMarker(m) {
					weightsState = "weights:cached"
				}
				fmt.Fprintf(out, "%s [%s%s, %s]\n", refName, bundleState, variant, weightsState)
			}
			return nil
		},
	}
}

func modelsEnvsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "envs [ref]",
		Short: "List bundle runtime environments and this machine's match",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			gpu := preflight.DetectGPU()
			fmt.Fprintf(out, "FlashHub API: %s\n\n", flashhub.APIBase())
			if gpu == nil {
				fmt.Fprintln(out, "[!] No NVIDIA GPU detected; cannot match an environment.")
			}

			var refs []string
			if len(args) == 1 {
				refs = []string{args[0]}
			} else {
				for _, m := range bundleMarkers() {
					if r := strOf(m["ref"]); r != "" {
						refs = append(refs, r)
					} else if ck := fmt.Sprint(m["cache_key"]); ck != "" {
						refs = append(refs, ck)
					}
				}
				if len(refs) == 0 {
					fmt.Fprintln(out, "No cached presets. Pass a ref or run flashcli bundle sync <ref> first.")
					return nil
				}
			}

			for _, refStr := range refs {
				modelsEnvsOne(out, refStr, gpu)
				fmt.Fprintln(out, "")
			}
			return nil
		},
	}
}

func weightsCachedFromMarker(m map[string]any) bool {
	key := fmt.Sprint(m["cache_key"])
	if key == "" || key == "<nil>" {
		return false
	}
	rel := "checkpoint"
	if br := strOf(m["bundle_root"]); br != "" {
		if man, err := manifest.Load(br); err == nil {
			if _, r, _, err := weights.ManifestSpecs(man, strOf(m["variant"])); err == nil && r != "" {
				rel = r
			}
		}
	}
	dir := filepath.Join(paths.Models(), filepath.FromSlash(key), filepath.FromSlash(rel))
	if cp, ok := weights.ReadMarker(dir); ok {
		if info, err := os.Stat(cp); err == nil && info.IsDir() {
			return true
		}
	}
	return false
}

func modelsEnvsOne(out interface{ Write([]byte) (int, error) }, refStr string, gpu *preflight.GpuInfo) {
	p, err := ref.Parse(refStr)
	if err != nil {
		fmt.Fprintf(out, "%s: invalid ref — %s\n", refStr, err)
		return
	}
	fmt.Fprintf(out, "%s:\n", refStr)
	fmt.Fprintf(out, "  repo: %s\n", repoURLFor(p))

	m, _ := loadManifestForRef(refStr, p)
	if m == nil {
		return
	}
	if gpu == nil {
		return
	}
	abi := m.PythonABIOrEmpty()
	hostKey := preflight.VariantDirName(gpu, abi)
	if abi == "" {
		fmt.Fprintf(out, "  this machine: %s (native, no python_abi)\n", hostKey)
	} else {
		fmt.Fprintf(out, "  this machine: %s (python_abi=%s)\n", hostKey, abi)
		if py, perr := venv.ResolveBasePython(abi); perr == nil {
			fmt.Fprintf(out, "  python 3.%s: %s\n", abi[1:], py)
		} else {
			fmt.Fprintf(out, "  python 3.%s: NOT FOUND (will auto-install on run, or set FLASHCLI_PY%s_BIN)\n", abi[1:], abi)
		}
	}
	keys := make([]string, 0, len(m.RuntimeMap()))
	for k := range m.RuntimeMap() {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	match := preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), hostKey)
	fmt.Fprintf(out, "  supported (%d):\n", len(keys))
	for _, k := range keys {
		mark := ""
		if k == match {
			mark = " ← match"
		}
		fmt.Fprintf(out, "    - %s%s\n", k, mark)
	}
}

func repoURLFor(p ref.Parsed) string {
	if p.Local {
		return "(local)"
	}
	u, err := flashhub.RepoURL(flashhub.APIBase(), p.Namespace, p.Name, p.Version)
	if err != nil {
		return ""
	}
	return u
}

// loadManifestForRef loads a manifest for a local path, cached bundle, or by
// downloading the FlashHub manifest (no full sync).
func loadManifestForRef(refStr string, p ref.Parsed) (*manifest.Manifest, error) {
	if p.Local {
		abs, err := filepath.Abs(refStr)
		if err != nil {
			return nil, err
		}
		return manifest.Load(abs)
	}
	cacheKey := weights.TreeKey(p.Name, p.Version)
	marker := runtime.ReadPresetMarker(cacheKey)
	if br := strOf(marker["bundle_root"]); br != "" {
		if m, err := manifest.Load(br); err == nil {
			return m, nil
		}
	}
	repoURL := repoURLFor(p)
	if repoURL == "" {
		return nil, fmt.Errorf("cannot resolve repo for %q", refStr)
	}
	client := flashhub.NewClient()
	dest := filepath.Join(paths.Cache(), "manifest", strings.ReplaceAll(cacheKey, "/", "_")+".json")
	data, err := client.DownloadManifest(context.Background(), repoURL, dest, false, true)
	if err != nil {
		return nil, err
	}
	return manifest.LoadData(data, filepath.Dir(dest))
}

func modelsShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <ref>",
		Short: "Show a preset's ref, cached runtime and paths",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			p, err := ref.Parse(args[0])
			if err != nil {
				return failed(cmd, err)
			}
			fmt.Fprintf(out, "flashcli %s\n", version.Version)
			fmt.Fprintf(out, "ref: %s\n", p.Name)
			if p.Variant != "" {
				fmt.Fprintf(out, "variant: %s\n", p.Variant)
			}
			key := refCacheKey(p)
			if p.Local {
				abs, _ := filepath.Abs(args[0])
				fmt.Fprintf(out, "local_root: %s\n", abs)
			} else {
				repoURL := repoURLFor(p)
				fmt.Fprintf(out, "FlashHub API: %s\n", flashhub.APIBase())
				fmt.Fprintf(out, "repo: %s\n", repoURL)
				fmt.Fprintf(out, "expected runtime_id: %s\n", runtime.IDFromRepo(repoURL, p.Name))
			}

			marker := runtime.ReadPresetMarker(key)
			if len(marker) == 0 {
				fmt.Fprintln(out, "cached preset marker: (none — run flashcli run/serve or bundle sync)")
			} else {
				fmt.Fprintln(out, "cached preset marker:")
				for _, k := range []string{"ref", "repo_url", "runtime_id", "bundle_root", "env_key", "source", "local_root"} {
					if v := strOf(marker[k]); v != "" {
						fmt.Fprintf(out, "  %s: %s\n", k, v)
					}
				}
				if rid := strOf(marker["runtime_id"]); rid != "" {
					rm := runtime.ReadMarker(rid)
					if sha := strOf(rm["manifest_sha256"]); sha != "" {
						fmt.Fprintf(out, "  manifest_sha256: %s\n", sha)
					}
				}
				if !p.Local {
					expected := repoURLFor(p)
					if cached := strOf(marker["repo_url"]); cached != "" && expected != "" && cached != expected {
						fmt.Fprintf(out, "  [!] cached repo differs from ref — run: flashcli bundle sync %s --force\n", p.Name)
					}
				}
			}

			if weightsCachedFor(p, args[0]) {
				fmt.Fprintln(out, "weights: cached")
			} else {
				fmt.Fprintln(out, "weights: missing")
			}
			return nil
		},
	}
}
