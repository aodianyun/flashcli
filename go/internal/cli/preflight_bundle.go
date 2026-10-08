package cli

import (
	"context"
	"path/filepath"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/cuda"
	"github.com/aodianyun/flashcli/go/internal/errs"
	"github.com/aodianyun/flashcli/go/internal/hostabi"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/native"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// preflightBundle resolves the host runtime env key and validates the selected
// native cell (+ host ABI, and CUDA userland when a venv interpreter is given).
// Mirrors flashcli.bundle.preflight.run_preflight + ensure_runtime_from_*.
func preflightBundle(m *manifest.Manifest, root, venvPython string, quiet, autoInstall bool) (string, error) {
	if envBool("FLASHCLI_SKIP_PREFLIGHT") {
		return resolveEnvKey(m), nil
	}
	abi, err := m.PythonABI()
	if err != nil {
		return "", err
	}
	gpu := preflight.DetectGPU()
	hostKey := ""
	if gpu != nil {
		hostKey = preflight.VariantDirName(gpu, abi)
	}
	envKey := preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), hostKey)
	if envKey == "" {
		if gpu == nil {
			return "", errs.Envf("No NVIDIA GPU detected (nvidia-smi unavailable). Model bundles require a CUDA GPU for inference.")
		}
		return "", errs.Envf("Bundle %q does not support this machine's runtime environment %q. Supported: %s", m.Name, hostKey, strings.Join(sortedKeys(m.RuntimeMap()), ", "))
	}
	rel := m.RuntimeMap()[envKey]
	dir := filepath.Join(root, filepath.FromSlash(rel))
	if len(native.DiscoverModuleBases(dir, envKey)) == 0 {
		return "", errs.Envf("Bundle %s missing native .so under %s for %q. Run pack/release or build into runtime/%s/.", root, rel, envKey, envKey)
	}
	if err := hostabi.Ensure(native.NativeSOPaths(dir, envKey), quiet); err != nil {
		return "", err
	}
	if venvPython != "" {
		if parsed, perr := preflight.ParseEnvKey(envKey); perr == nil {
			if err := cuda.Ensure(context.Background(), venvPython, parsed.CudaTag, quiet, autoInstall, nil); err != nil {
				return "", err
			}
		}
	}
	return envKey, nil
}

func sortedKeys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// ensureBundleRuntime runs preflight, builds the bundle venv, then runs the
// CUDA userland check. Used by pull / bundle sync (mirrors prepare_bundle_runtime).
func ensureBundleRuntime(m *manifest.Manifest, bundleRoot, version, variant string, quiet, noAutoInstall bool) (string, string, error) {
	runtimeID := runtime.IDFromPath(bundleRoot, m.Name)
	if version != "local" {
		if marker := runtime.ReadPresetMarker(weights.CacheKey(m.Name, version, variant)); marker != nil {
			if rid := strOf(marker["runtime_id"]); rid != "" {
				runtimeID = rid
			}
		}
	}
	if _, err := preflightBundle(m, bundleRoot, "", quiet, !noAutoInstall); err != nil {
		return "", "", err
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
	if _, err := preflightBundle(m, bundleRoot, python, quiet, !noAutoInstall); err != nil {
		return "", "", err
	}
	return runtimeID, python, nil
}
