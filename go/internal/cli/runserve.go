package cli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/cuda"
	"github.com/aodianyun/flashcli/go/internal/inferexec"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeabi"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

func runCmd() *cobra.Command   { return runServeCmd("run") }
func serveCmd() *cobra.Command { return runServeCmd("serve") }

func runServeCmd(capability string) *cobra.Command {
	short := "Run a bundle once"
	if capability == "serve" {
		short = "Serve a bundle over HTTP"
	}
	return &cobra.Command{
		Use:                capability + " <ref> [OPTIONS]",
		Short:              short,
		DisableFlagParsing: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				fmt.Fprintf(cmd.OutOrStderr(), "usage: flashcli %s <ref> [OPTIONS]\n", capability)
				return ErrFailed
			}
			hf := peelHostFlags(args)
			if hf.Ref == "" {
				if hf.WantsHelp {
					fmt.Fprintf(cmd.OutOrStdout(), "Usage: flashcli %s REF[@variant] [OPTIONS]\nTry 'flashcli %s <ref> --help' for bundle-specific options.\n", capability, capability)
					return nil
				}
				fmt.Fprintf(cmd.OutOrStderr(), "usage: flashcli %s <ref> [OPTIONS]\n", capability)
				return ErrFailed
			}
			if err := runPrelude(capability, args, hf); err != nil {
				return failed(cmd, err)
			}
			return nil
		},
	}
}

func capSpec(m *manifest.Manifest, capability string) *manifest.EntrySpec {
	if capability == "run" {
		return m.EntryRun
	}
	return m.EntryServe
}

func runPrelude(capability string, args []string, hf hostFlags) error {
	quiet := hf.Quiet || envBool("FLASHCLI_QUIET")
	bundleRoot, version, variant, err := ensureBundleRef(hf.Ref, quiet, false)
	if err != nil {
		return err
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil {
		return err
	}
	if _, err := manifest.ResolveVariant(m, variant); err != nil {
		return err
	}
	spec := capSpec(m, capability)
	if spec == nil {
		return fmt.Errorf("bundle %q does not support %s", m.Name, capability)
	}
	if hf.WantsHelp {
		fmt.Fprint(os.Stdout, bundleHelp(m, capability, variant))
		return nil
	}
	if version == "local" {
		if _, err := writeLocalMarkers(m, bundleRoot, variant); err != nil {
			return err
		}
	}
	if _, err := preflightBundle(m, bundleRoot, "", quiet, !hf.NoAutoInstall); err != nil {
		return err
	}
	switch spec.Kind {
	case "native-exec":
		return runNativeExec(m, spec, bundleRoot, version, variant, capability, args, hf)
	case "native-abi":
		return runNativeABI(m, spec, bundleRoot, version, variant, capability, hf)
	default:
		return runPythonBackend(m, bundleRoot, version, variant, capability, args, hf)
	}
}

func runPythonBackend(m *manifest.Manifest, root, version, variant, capability string, args []string, hf hostFlags) error {
	// Bundle venv lives under the sync marker's runtime id (repo-derived) for
	// FlashHub refs; local paths use the path-derived id.
	runtimeID := runtime.IDFromPath(root, m.Name)
	if version != "local" {
		if marker := runtime.ReadPresetMarker(weights.CacheKey(m.Name, version, variant)); marker != nil {
			if rid := strOf(marker["runtime_id"]); rid != "" {
				runtimeID = rid
			}
		}
	}

	quiet := hf.Quiet || envBool("FLASHCLI_QUIET")
	_, _, extraEnv, err := resolveWeights(m, root, version, variant, quiet, hf)
	if err != nil {
		return err
	}
	python, err := venv.Ensure(context.Background(), runtimeID, m, venv.Options{
		SkipSetup:     envBool("FLASHCLI_SKIP_VENV_SETUP"),
		Force:         envBool("FLASHCLI_FORCE_VENV"),
		Quiet:         quiet,
		NoAutoInstall: hf.NoAutoInstall,
	})
	if err != nil {
		return err
	}
	if !envBool("FLASHCLI_SKIP_PREFLIGHT") {
		if envKey := resolveEnvKey(m); envKey != "" {
			if parsed, perr := preflight.ParseEnvKey(envKey); perr == nil {
				if err := cuda.Ensure(context.Background(), python, parsed.CudaTag, quiet, !hf.NoAutoInstall, nil); err != nil {
					return err
				}
			}
		}
	}

	// Forward the original argv (ref + flags) to infer, as reexec.py does.
	argv := inferexec.BuildArgv(python, capability, args)
	env := inferexec.BuildEnv(os.Environ(), runtimeID, root, filepath.Dir(filepath.Dir(python)))
	env = append(env, extraEnv...)
	if spec := capSpec(m, capability); spec != nil && spec.Mode != "script" && hf.MTPCheckpoint != "" {
		env = append(env, "FLASHRT_QWEN36_MTP_CKPT_DIR="+hf.MTPCheckpoint)
	}
	return inferexec.Exec(python, argv, env)
}

func runNativeABI(m *manifest.Manifest, entry *manifest.EntrySpec, root, version, variant, capability string, hf hostFlags) error {
	if capability == "serve" {
		return fmt.Errorf("native-abi serve is not implemented yet")
	}
	key := ""
	if gpu := preflight.DetectGPU(); gpu != nil {
		if abi, abiErr := m.PythonABI(); abiErr == nil {
			key = preflight.ResolveRuntimeEnvKey(m.RuntimeMap(), preflight.VariantDirName(gpu, abi))
		}
	}
	if key == "" {
		key = strings.TrimSpace(os.Getenv("FLASHCLI_RUNTIME_ENV_KEY"))
	}
	if key == "" {
		key = m.SoleRuntimeKey()
	}
	if key == "" {
		return errors.New("bundle has no matching runtime env key; set FLASHCLI_RUNTIME_ENV_KEY")
	}
	rel, ok := m.RuntimeMap()[key]
	if !ok {
		return fmt.Errorf("runtime key %q not found in manifest", key)
	}

	spec, err := nativeabi.SpecFromEntry(entry)
	if err != nil {
		return err
	}
	checkpoint, extra, env, err := resolveWeights(m, root, version, variant, hf.Quiet, hf)
	if err != nil {
		return err
	}
	for _, kv := range env {
		if i := strings.IndexByte(kv, '='); i > 0 {
			_ = os.Setenv(kv[:i], kv[i+1:])
		}
	}
	ph := nativeexec.Placeholders{
		Checkpoint: checkpoint,
		BundleRoot: root,
		ModelsDir:  paths.Models(),
		Preset:     m.Name,
		Variant:    variant,
		RuntimeDir: filepath.Join(root, filepath.FromSlash(rel)),
		Extra:      extra,
	}
	lib, err := nativeabi.Open(spec, ph)
	if err != nil {
		return err
	}
	defer lib.Close()

	out := map[string]any{
		"kind":        "native-abi",
		"abi_version": lib.ABIVersion,
		"struct_size": lib.StructSize,
		"config":      lib.ConfigJSON(),
	}
	blob, _ := json.MarshalIndent(out, "", "  ")
	fmt.Fprintln(os.Stdout, string(blob))
	return nil
}

// resolveWeights prepares weights + manifest/post-pull env. When --checkpoint is
// given the cache download is skipped.
func resolveWeights(m *manifest.Manifest, abs, version, variant string, quiet bool, hf hostFlags) (string, map[string]string, []string, error) {
	mainSpec, _, extraSpecs, err := weights.ManifestSpecs(m, variant)
	if err != nil {
		return "", nil, nil, err
	}
	checkpoint := ""
	var env map[string]string
	switch {
	case hf.Checkpoint != "":
		checkpoint, err = filepath.Abs(hf.Checkpoint)
		if err != nil {
			return "", nil, nil, err
		}
		if _, statErr := os.Stat(checkpoint); statErr != nil {
			return "", nil, nil, fmt.Errorf("Checkpoint not found: %s", checkpoint)
		}
		env = weights.EnvMap(m, variant)
	case envBool("FLASHCLI_SKIP_WEIGHTS"):
		env = weights.EnvMap(m, variant)
	default:
		checkpoint, env, err = weights.PrepareBundle(context.Background(), m, version, variant, quiet)
		if err != nil {
			return "", nil, nil, err
		}
	}
	_ = mainSpec
	extra := map[string]string{}
	for key, ex := range extraSpecs {
		extra[key] = weights.ExtraWeightDest(checkpoint, abs, key, ex)
	}
	return checkpoint, extra, mapEnv(env), nil
}

func mapEnv(env map[string]string) []string {
	out := make([]string, 0, len(env))
	for k, v := range env {
		out = append(out, k+"="+v)
	}
	sort.Strings(out)
	return out
}

func runNativeExec(m *manifest.Manifest, entry *manifest.EntrySpec, root, version, variant, capability string, args []string, hf hostFlags) error {
	spec, err := nativeexec.SpecFromEntry(entry)
	if err != nil {
		return err
	}
	quiet := hf.Quiet || envBool("FLASHCLI_QUIET")
	checkpoint, extra, extraEnv, err := resolveWeights(m, root, version, variant, quiet, hf)
	if err != nil {
		return err
	}
	ph := nativeexec.Placeholders{
		Checkpoint: checkpoint,
		BundleRoot: root,
		ModelsDir:  paths.Models(),
		Preset:     m.Name,
		Variant:    variant,
		Extra:      extra,
	}
	process, err := nativeexec.Start(context.Background(), spec, ph, extraEnv)
	if err != nil {
		return err
	}
	defer func() { _ = process.Close(context.Background()) }()

	if capability == "serve" {
		if spec.Transport == "http" {
			fmt.Fprintln(os.Stderr, "native-exec serve endpoint ready")
			waitForSignal()
			return nil
		}
		return fmt.Errorf("native-exec serve over stdio is not implemented yet")
	}

	out, err := process.Run(context.Background(), parseFlags(args))
	if err != nil {
		return err
	}
	blob, _ := json.MarshalIndent(out, "", "  ")
	fmt.Fprintln(os.Stdout, string(blob))
	return nil
}

// parseFlags maps non-host --flags to a payload for native backends.
func parseFlags(args []string) map[string]any {
	out := map[string]any{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if !strings.HasPrefix(a, "--") {
			continue
		}
		key := strings.TrimPrefix(a, "--")
		if eq := strings.IndexByte(key, '='); eq >= 0 {
			if !hostFlagNames["--"+key[:eq]] {
				out[key[:eq]] = key[eq+1:]
			}
			continue
		}
		if hostFlagNames["--"+key] {
			if i+1 < len(args) && !strings.HasPrefix(args[i+1], "--") {
				i++
			}
			continue
		}
		if i+1 < len(args) && !strings.HasPrefix(args[i+1], "--") {
			out[key] = args[i+1]
			i++
		} else {
			out[key] = true
		}
	}
	return out
}

func waitForSignal() {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGINT, syscall.SIGTERM)
	<-ch
}

func envBool(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}
