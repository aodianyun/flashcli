package host

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/cuda"
	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/hostabi"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/native"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/version"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// EnsureBundle resolves a local path or FlashHub ref to a local bundle root,
// syncing the tree on first use.
func EnsureBundle(refStr string, quiet, force bool) (root, ver, variant string, err error) {
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
	cacheKey := weights.TreeKey(p.Name, p.Version)
	bundleDir := filepath.Join(paths.Bundles(), filepath.FromSlash(cacheKey))
	manifestPath := filepath.Join(bundleDir, flashhub.ManifestPath)
	doneMarker := filepath.Join(bundleDir, flashhub.MarkerName)
	if _, err := os.Stat(doneMarker); err == nil && !force {
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
	envKey := ResolveEnvKey(m)
	if envKey == "" {
		return "", "", "", fmt.Errorf("bundle %q has no runtime environment for this machine", m.Name)
	}
	if _, err := client.SyncBundle(ctx, repoURL, bundleDir, m.RuntimeMap()[envKey], quiet); err != nil {
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
		"variant":     variant,
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
		"weights_key": weights.StoreKeyFor(m, p.Version),
		"variant":     variant,
	}); err != nil {
		return "", "", "", err
	}
	if !quiet {
		fmt.Fprintf(os.Stderr, "Synced %s -> %s (env %s)\n", refStr, bundleDir, envKey)
	}
	return bundleDir, p.Version, variant, nil
}

// WriteLocalMarkers records runtime + preset markers for a local bundle.
func WriteLocalMarkers(m *manifest.Manifest, root, variant string) (string, error) {
	runtimeID := runtime.IDFromPath(root, m.Name)
	envKey := ResolveEnvKey(m)
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
	key := weights.CacheKeyFor(m, "local")
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

// ResolveEnvKey resolves the runtime cell for the current host. It supports v4
// exact matches, explicit fallback blocks, and FLASHCLI_RUNTIME_ENV_KEY.
func ResolveEnvKey(m *manifest.Manifest) string {
	hostKey := preflight.HostEnvKey(preflight.DetectGPU(), m.PythonABIOrEmpty())
	key, err := m.ResolveEnvKey(hostKey)
	if err != nil {
		return ""
	}
	return key
}

// ApplyEnv applies the selected v4 environment overlay. v3 manifests are
// returned unchanged.
func ApplyEnv(m *manifest.Manifest) (*manifest.Manifest, error) {
	if m.FormatVersion < manifest.FormatVersionV4 {
		return m, nil
	}
	key := ResolveEnvKey(m)
	if key == "" {
		return nil, fmt.Errorf("bundle %q has no runtime environment for this host", m.Name)
	}
	return m.ApplyEnv(key)
}

// PreflightBundle validates the selected runtime cell on this host.
func PreflightBundle(m *manifest.Manifest, root, venvPython string, quiet, autoInstall bool) (string, error) {
	if envBool("FLASHCLI_SKIP_PREFLIGHT") {
		return ResolveEnvKey(m), nil
	}
	hostKey := preflight.HostEnvKey(preflight.DetectGPU(), m.PythonABIOrEmpty())
	envKey, err := m.ResolveEnvKey(hostKey)
	if err != nil || envKey == "" {
		if preflight.DetectGPU() == nil {
			return "", errs.Envf("No NVIDIA GPU detected (nvidia-smi unavailable). Model bundles require a CUDA GPU for inference.")
		}
		return "", errs.Envf("Bundle %q does not support this machine's runtime environment %q. Supported: %s", m.Name, hostKey, strings.Join(m.EnvironmentKeys(), ", "))
	}
	rel := m.RuntimeMap()[envKey]
	if rel == "" {
		return envKey, nil
	}
	dir := filepath.Join(root, filepath.FromSlash(rel))
	if err := EnsureELFInspector(quiet, autoInstall); err != nil {
		return "", err
	}
	if len(native.DiscoverModuleBases(dir, "")) == 0 && !hasSubstrateSO(dir) {
		return "", errs.Envf("Bundle %s missing native .so under %s for environment %q. Run pack/release or build into runtime/%s/.", root, rel, envKey, rel)
	}
	if err := hostabi.Ensure(native.NativeSOPaths(dir, ""), quiet); err != nil {
		return "", err
	}
	if venvPython != "" {
		if parsed, perr := preflight.ParseEnvKey(envKey); perr == nil && parsed.CudaTag != "" {
			if err := cuda.Ensure(context.Background(), venvPython, parsed.CudaTag, quiet, autoInstall, nil); err != nil {
				return "", err
			}
		}
	}
	return envKey, nil
}

// EnsureRuntime runs preflight, builds the bundle venv, then validates CUDA.
func EnsureRuntime(m *manifest.Manifest, bundleRoot, ver, variant string, quiet, noAutoInstall bool) (string, string, error) {
	var err error
	m, err = ApplyEnv(m)
	if err != nil {
		return "", "", err
	}
	runtimeID := runtime.IDFromPath(bundleRoot, m.Name)
	if ver != "local" {
		if marker := runtime.ReadPresetMarker(weights.CacheKeyFor(m, ver)); marker != nil {
			if rid := stringValue(marker["runtime_id"]); rid != "" {
				runtimeID = rid
			}
		}
	}
	if _, err := PreflightBundle(m, bundleRoot, "", quiet, !noAutoInstall); err != nil {
		return "", "", err
	}
	if !m.NeedsPythonVenv() {
		return runtimeID, "", nil
	}
	if envBool("FLASHCLI_SKIP_VENV_SETUP") {
		return runtimeID, "", nil
	}
	python, err := venv.Ensure(context.Background(), runtimeID, m, venv.Options{
		SkipSetup:     envBool("FLASHCLI_SKIP_VENV_SETUP"),
		NoAutoInstall: noAutoInstall,
		Quiet:         quiet,
	})
	if err != nil {
		return "", "", err
	}
	if _, err := PreflightBundle(m, bundleRoot, python, quiet, !noAutoInstall); err != nil {
		return "", "", err
	}
	return runtimeID, python, nil
}

// Pull syncs the bundle, prepares the runtime, and downloads weights.
func Pull(ctx context.Context, refStr string, opts PullOptions) (PullResult, error) {
	emit := func(phase, message string) {
		if opts.Progress != nil {
			opts.Progress(PullEvent{Phase: phase, Message: message, Ref: refStr})
		}
	}
	emit("resolve", "resolving bundle")
	bundleRoot, ver, variant, err := EnsureBundle(refStr, opts.Quiet, false)
	if err != nil {
		return PullResult{}, err
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil {
		return PullResult{}, err
	}
	m, err = ApplyEnv(m)
	if err != nil {
		return PullResult{}, err
	}
	if _, err := manifest.ResolveVariant(m, variant); err != nil {
		return PullResult{}, err
	}
	emit("runtime", "preparing runtime")
	if _, _, err := EnsureRuntime(m, bundleRoot, ver, variant, opts.Quiet, opts.NoAutoInstall); err != nil {
		return PullResult{}, err
	}
	emit("weights", "downloading weights")
	checkpoint, _, err := weights.PrepareBundle(ctx, m, ver, variant, opts.Quiet, true)
	if err != nil {
		return PullResult{}, err
	}
	emit("done", checkpoint)
	return PullResult{BundleRoot: bundleRoot, Version: ver, Variant: variant, Checkpoint: checkpoint}, nil
}

func hasSubstrateSO(dir string) bool {
	matches, _ := filepath.Glob(filepath.Join(dir, "substrate", "*.so"))
	return len(matches) > 0
}

func envBool(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}
