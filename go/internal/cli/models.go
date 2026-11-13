package cli

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"text/tabwriter"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/host"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/system"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/version"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

func modelsCmd() *cobra.Command {
	root := &cobra.Command{
		Use:   "models",
		Short: "Model/bundle cache utilities",
	}
	root.AddCommand(modelsListCmd(), modelsShowCmd())
	return root
}

// bundleMarkers lists preset markers under Bundles().
func bundleMarkers() []map[string]any {
	return host.Markers()
}

func weightsCachedFor(p ref.Parsed, refStr string) bool {
	ver := p.Version
	if p.Local || ver == "" {
		ver = "local"
	}
	key := weights.TreeKey(p.Name, ver)
	rel := "checkpoint"
	m, err := loadManifestForRef(refStr, p)
	if err == nil {
		weightsKey := weights.StoreKeyFor(m, ver)
		cached, _, _, _ := host.WeightsInfo(m, weightsKey, p.Variant)
		return cached
	}
	// Keep a marker-only fallback for offline/foreign caches whose manifest
	// cannot be loaded here; readiness is unavailable in that case.
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
		Short: "List locally synced bundles with bundle/runtime/weights disk usage",
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			models, err := host.ListModels()
			if err != nil {
				return err
			}
			if len(models) == 0 {
				fmt.Fprintln(out, "No cached presets. Run flashcli run <ref> or flashcli bundle sync <ref>.")
				return nil
			}
			w := tabwriter.NewWriter(out, 0, 0, 2, ' ', 0)
			fmt.Fprintln(w, "REF\tBUNDLE\tBUNDLE SIZE\tRUNTIME\tRUNTIME SIZE\tWEIGHTS\tWEIGHTS SIZE\tDIR")
			for _, model := range models {
				bundleState := "missing"
				if model.BundleCached {
					bundleState = "cached"
				}
				weightsState := "missing"
				if model.WeightsCached {
					weightsState = "cached"
				}
				dir := filepath.ToSlash(filepath.Join(cacheRootDisplay(), "models", filepath.FromSlash(model.WeightsKey)))
				fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n",
					model.Ref, bundleState, humanSize(model.BundleBytes),
					model.RuntimeID, humanSize(model.RuntimeBytes),
					weightsState, humanSize(model.WeightsBytes), dir)
			}
			return w.Flush()
		},
	}
}

func markerWeightsKey(marker map[string]any, fallback string) string {
	return host.MarkerWeightsKey(marker, fallback, strOf(marker["bundle_root"]))
}

func cacheRootDisplay() string {
	home := paths.Home()
	if userHome, err := os.UserHomeDir(); err == nil && home == filepath.Join(userHome, ".flashcli") {
		return "~/.flashcli"
	}
	return filepath.ToSlash(home)
}

func bundleRootUsable(root string) bool {
	return host.BundleRootUsable(root)
}

func weightsCachedFromMarker(m map[string]any) bool {
	key := fmt.Sprint(m["cache_key"])
	if key == "" || key == "<nil>" {
		return false
	}
	return host.WeightsCachedForMarker(m, key)
}

func modelsEnvsFromMarker(out interface{ Write([]byte) (int, error) }, refStr string, marker map[string]any, gpu *preflight.GpuInfo) {
	p, err := ref.Parse(refStr)
	if err != nil {
		fmt.Fprintf(out, "%s: invalid ref — %s\n", refStr, err)
		return
	}
	fmt.Fprintf(out, "%s:\n", refStr)
	fmt.Fprintf(out, "  repo: %s\n", repoURLFor(p))

	br := strOf(marker["bundle_root"])
	if br == "" {
		return
	}
	m, err := manifest.Load(br)
	if err != nil {
		return
	}
	modelsEnvBlock(out, m, gpu)
}

func modelsEnvBlock(out interface{ Write([]byte) (int, error) }, m *manifest.Manifest, gpu *preflight.GpuInfo) {
	abi := m.PythonABIOrEmpty()
	hostKey := preflight.HostEnvKey(gpu, abi)
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
	keys := m.EnvironmentKeys()
	match, _ := m.ResolveEnvKey(hostKey)
	fmt.Fprintf(out, "  supported (%d):\n", len(keys))
	for _, k := range keys {
		mark := ""
		if k == match {
			mark = " ← match"
		}
		fmt.Fprintf(out, "    - %s%s\n", k, mark)
	}
}

func printSystemInfo(out interface{ Write([]byte) (int, error) }, m *manifest.Manifest, runtimeID string) {
	reqs := m.SystemRequires()
	if len(reqs) == 0 {
		return
	}
	python := ""
	if runtimeID != "" {
		if py, err := runtime.VenvPython(runtimeID); err == nil {
			python = py
		}
	}
	statuses, err := system.Check(context.Background(), reqs, python)
	if err != nil {
		fmt.Fprintf(out, "system:\n  [!] %s\n", err)
		return
	}
	fmt.Fprintln(out, "system:")
	for _, st := range statuses {
		state := "present"
		if !st.Checked {
			state = st.Detail
		} else if !st.Present {
			hint := system.PackageHint(st.Capability, m.PythonABIOrEmpty())
			state = "missing"
			if hint != "" {
				state += " (install: " + hint + ")"
			}
		}
		fmt.Fprintf(out, "  %-18s %s\n", st.Capability, state)
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
		Use:   "show [ref]",
		Short: "Show a cached preset, runtime env, and paths (or list cached refs)",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			gpu := preflight.DetectGPU()
			if len(args) == 0 {
				return showCachedEnvs(out, gpu)
			}
			return showOne(out, args[0], gpu)
		},
	}
}

func showCachedEnvs(out interface{ Write([]byte) (int, error) }, gpu *preflight.GpuInfo) error {
	fmt.Fprintf(out, "FlashHub API: %s\n\n", flashhub.APIBase())
	if gpu == nil {
		fmt.Fprintln(out, "[!] No NVIDIA GPU detected; only CPU fallback environments can match.")
	}
	markers := bundleMarkers()
	if len(markers) == 0 {
		fmt.Fprintln(out, "No cached presets. Pass a ref or run flashcli bundle sync <ref> first.")
		return nil
	}
	for _, marker := range markers {
		refStr := strOf(marker["ref"])
		if refStr == "" {
			refStr = fmt.Sprint(marker["cache_key"])
		}
		modelsEnvsFromMarker(out, refStr, marker, gpu)
		fmt.Fprintln(out, "")
	}
	return nil
}

func showOne(out interface{ Write([]byte) (int, error) }, refStr string, gpu *preflight.GpuInfo) error {
	p, err := ref.Parse(refStr)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "flashcli %s\n", version.Version)
	fmt.Fprintf(out, "ref: %s\n", refStr)
	if p.Variant != "" {
		fmt.Fprintf(out, "variant: %s\n", p.Variant)
	}
	key := refCacheKey(p)
	expectedRID := ""
	if p.Local {
		abs, _ := filepath.Abs(refStr)
		fmt.Fprintf(out, "local_root: %s\n", abs)
		expectedRID = runtime.IDFromPath(abs, p.Name)
	} else {
		repoURL := repoURLFor(p)
		fmt.Fprintf(out, "repo: %s\n", repoURL)
		expectedRID = runtime.IDFromRepo(repoURL, p.Name)
	}
	if expectedRID != "" {
		fmt.Fprintf(out, "runtime_id: %s\n", expectedRID)
	}

	m, _ := loadManifestForRef(refStr, p)
	if gpu == nil {
		fmt.Fprintln(out, "[!] No NVIDIA GPU detected; cannot match an environment.")
	} else if m != nil {
		fmt.Fprintln(out, "runtime env:")
		modelsEnvBlock(out, m, gpu)
	}
	if m != nil {
		printBuildInfo(out, m)
		printSystemInfo(out, m, expectedRID)
	}

	marker := runtime.ReadPresetMarker(key)
	if len(marker) == 0 {
		fmt.Fprintln(out, "cache: not prepared (run flashcli run/serve or bundle sync)")
	} else {
		fmt.Fprintln(out, "cache:")
		br := strOf(marker["bundle_root"])
		if p.Local {
			if abs, _ := filepath.Abs(refStr); filepath.Clean(br) != filepath.Clean(abs) {
				fmt.Fprintf(out, "  bundle_root: %s\n", br)
			}
		} else if br != "" {
			fmt.Fprintf(out, "  bundle_root: %s\n", br)
		}
		if rid := strOf(marker["runtime_id"]); rid != "" && rid != expectedRID {
			fmt.Fprintf(out, "  runtime_id: %s (expected %s)\n", rid, expectedRID)
		}
		if source := strOf(marker["source"]); source != "" {
			fmt.Fprintf(out, "  source: %s\n", source)
		}
		if !p.Local {
			expected := repoURLFor(p)
			if cached := strOf(marker["repo_url"]); cached != "" && expected != "" && cached != expected {
				fmt.Fprintf(out, "  [!] cached repo differs from ref — run: flashcli bundle sync %s --force\n", p.Name)
			}
		}
	}

	printWeightsInfo(out, m, p.Variant, weightsCachedFor(p, refStr))
	return nil
}

func printBuildInfo(out interface{ Write([]byte) (int, error) }, m *manifest.Manifest) {
	build, _ := m.Raw["build"].(map[string]any)
	if len(build) == 0 {
		return
	}
	fmt.Fprintln(out, "build:")
	if sources, ok := build["sources"].([]any); ok && len(sources) > 0 {
		for _, item := range sources {
			source, _ := item.(map[string]any)
			name := strOf(source["name"])
			repo := strOf(source["source"])
			commit := strOf(source["commit"])
			if name == "" && repo == "" && commit == "" {
				continue
			}
			fmt.Fprintf(out, "  %s: %s @ %s\n", name, repo, commit)
		}
		return
	}
	for _, key := range []string{"source", "commit", "flashrt_tag", "git_commit", "git_ref", "build_id", "native_artifact_tag"} {
		if value := strOf(build[key]); value != "" {
			fmt.Fprintf(out, "  %s: %s\n", key, value)
		}
	}
}

func manifestVariantNames(m *manifest.Manifest) []string {
	raw, _ := m.Raw["variants"].(map[string]any)
	names := make([]string, 0, len(raw))
	for name := range raw {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func printWeightsInfo(out interface{ Write([]byte) (int, error) }, m *manifest.Manifest, variant string, cached bool) {
	if m == nil {
		fmt.Fprintln(out, "weights:")
		fmt.Fprintln(out, "  source: unknown (manifest unavailable)")
		fmt.Fprintf(out, "  status: %s\n", statusWord(cached))
		return
	}
	main, rel, extras, err := weights.ManifestSpecs(m, variant)
	if err != nil {
		if variant == "" {
			if names := manifestVariantNames(m); len(names) > 0 {
				fmt.Fprintln(out, "weights:")
				fmt.Fprintf(out, "  variant required: %s\n", strings.Join(names, ", "))
				for _, name := range names {
					spec, specRel, specExtras, specErr := weights.ManifestSpecs(m, name)
					if specErr != nil {
						continue
					}
					fmt.Fprintf(out, "  @%s:\n", name)
					printWeightsSpec(out, "    ", spec)
					if specRel != "" {
						fmt.Fprintf(out, "    checkpoint: %s\n", specRel)
					}
					printExtraWeights(out, "    ", specExtras)
				}
				return
			}
		}
		fmt.Fprintln(out, "weights:")
		fmt.Fprintf(out, "  source: unavailable (%v)\n", err)
		fmt.Fprintf(out, "  status: %s\n", statusWord(cached))
		return
	}
	if !main.HasSource() && len(extras) == 0 {
		fmt.Fprintln(out, "weights: none declared in flashcli-bundle.json")
		fmt.Fprintf(out, "status: %s\n", statusWord(cached))
		return
	}
	fmt.Fprintln(out, "weights:")
	printWeightsSpec(out, "  ", main)
	if rel != "" {
		fmt.Fprintf(out, "  checkpoint: %s\n", rel)
	}
	printExtraWeights(out, "  ", extras)
	fmt.Fprintf(out, "  status: %s\n", statusWord(cached))
}

func statusWord(ok bool) string {
	if ok {
		return "cached"
	}
	return "missing"
}

func printWeightsSpec(out interface{ Write([]byte) (int, error) }, indent string, spec weights.Spec) {
	fmt.Fprintf(out, "%ssource: %s\n", indent, spec.Source)
	if spec.Repo != "" {
		fmt.Fprintf(out, "%srepo: %s\n", indent, spec.Repo)
	}
	if spec.Revision != "" {
		fmt.Fprintf(out, "%srevision: %s\n", indent, spec.Revision)
	}
	if spec.URL != "" {
		fmt.Fprintf(out, "%surl: %s\n", indent, spec.URL)
	}
	if spec.RelativeDir != "" {
		fmt.Fprintf(out, "%srelative_dir: %s\n", indent, spec.RelativeDir)
	}
	if len(spec.AllowPatterns) > 0 {
		fmt.Fprintf(out, "%sallow_patterns: %s\n", indent, strings.Join(spec.AllowPatterns, ", "))
	}
	if len(spec.RequireAnyPatterns) > 0 {
		fmt.Fprintf(out, "%srequire_any_patterns: %s\n", indent, strings.Join(spec.RequireAnyPatterns, ", "))
	}
	if spec.RequireNormStats {
		fmt.Fprintf(out, "%srequire_norm_stats: true\n", indent)
	}
}

func printExtraWeights(out interface{ Write([]byte) (int, error) }, indent string, extras map[string]weights.Spec) {
	if len(extras) == 0 {
		return
	}
	keys := make([]string, 0, len(extras))
	for k := range extras {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	fmt.Fprintf(out, "%sextra_weights:\n", indent)
	for _, k := range keys {
		fmt.Fprintf(out, "%s  %s:\n", indent, k)
		printWeightsSpec(out, indent+"    ", extras[k])
	}
}
