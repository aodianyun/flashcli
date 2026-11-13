package host

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/cuda"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/nativeexec"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/postpull"
	"github.com/aodianyun/flashcli/go/internal/preflight"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/venv"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// PrepareOptions controls bundle preparation.
type PrepareOptions struct {
	Quiet         bool
	NoAutoInstall bool
	Checkpoint    string
	MTPCheckpoint string
}

// Prepared is a prepared local model/bundle.
type Prepared struct {
	Ref        string
	Manifest   *manifest.Manifest
	BundleRoot string
	Version    string
	Variant    string
	RuntimeID  string
	Python     string
	Checkpoint string
	Extra      map[string]string
	Env        []string
}

// Prepare resolves, validates, prepares runtime/weights and (for Python
// bundles) the bundle venv. It is shared by CLI and flashserver.
func Prepare(ctx context.Context, refStr string, opts PrepareOptions) (Prepared, error) {
	bundleRoot, ver, variant, err := EnsureBundle(refStr, opts.Quiet, false)
	if err != nil {
		return Prepared{}, err
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil {
		return Prepared{}, err
	}
	m, err = ApplyEnv(m)
	if err != nil {
		return Prepared{}, err
	}
	if _, err := manifest.ResolveVariant(m, variant); err != nil {
		return Prepared{}, err
	}
	if ver == "local" {
		if _, err := WriteLocalMarkers(m, bundleRoot, variant); err != nil {
			return Prepared{}, err
		}
	}
	if _, err := PreflightBundle(m, bundleRoot, "", opts.Quiet, !opts.NoAutoInstall); err != nil {
		return Prepared{}, err
	}
	checkpoint, extra, env, err := ResolveWeights(ctx, m, bundleRoot, ver, variant, opts.Quiet, opts.Checkpoint)
	if err != nil {
		return Prepared{}, err
	}
	if err := EnsureSystemRequirements(m, "", opts.Quiet); err != nil {
		return Prepared{}, err
	}
	runtimeID := runtime.IDFromPath(bundleRoot, m.Name)
	if ver != "local" {
		if marker := runtime.ReadPresetMarker(weights.CacheKeyFor(m, ver)); marker != nil {
			if rid := stringValue(marker["runtime_id"]); rid != "" {
				runtimeID = rid
			}
		}
	}
	python := ""
	if m.NeedsPythonVenv() && !envBool("FLASHCLI_SKIP_VENV_SETUP") {
		python, err = venv.Ensure(ctx, runtimeID, m, venv.Options{
			SkipSetup:     envBool("FLASHCLI_SKIP_VENV_SETUP"),
			Force:         envBool("FLASHCLI_FORCE_VENV"),
			Quiet:         opts.Quiet,
			NoAutoInstall: opts.NoAutoInstall,
		})
		if err != nil {
			return Prepared{}, err
		}
		if err := venv.EnsureProtocolCacheSchema(ctx, python, venv.Options{Quiet: opts.Quiet, NoAutoInstall: opts.NoAutoInstall}); err != nil {
			return Prepared{}, err
		}
		if err := EnsureSystemRequirements(m, python, opts.Quiet); err != nil {
			return Prepared{}, err
		}
		if !envBool("FLASHCLI_SKIP_PREFLIGHT") {
			if envKey := ResolveEnvKey(m); envKey != "" {
				if parsed, perr := preflight.ParseEnvKey(envKey); perr == nil {
					if err := cuda.Ensure(ctx, python, parsed.CudaTag, opts.Quiet, !opts.NoAutoInstall, nil); err != nil {
						return Prepared{}, err
					}
				}
			}
		}
	}
	return Prepared{
		Ref: refStr, Manifest: m, BundleRoot: bundleRoot, Version: ver, Variant: variant,
		RuntimeID: runtimeID, Python: python, Checkpoint: checkpoint,
		Extra: extra, Env: mapEnv(env),
	}, nil
}

// ResolveWeights prepares weights and returns checkpoint, extra dirs, and env.
func ResolveWeights(ctx context.Context, m *manifest.Manifest, abs, ver, variant string, quiet bool, checkpointOverride string) (string, map[string]string, map[string]string, error) {
	mainSpec, _, extraSpecs, err := weights.ManifestSpecs(m, variant)
	if err != nil {
		return "", nil, nil, err
	}
	checkpoint := ""
	var env map[string]string
	switch {
	case checkpointOverride != "":
		checkpoint, err = filepath.Abs(checkpointOverride)
		if err != nil {
			return "", nil, nil, err
		}
		if _, err := os.Stat(checkpoint); err != nil {
			return "", nil, nil, fmt.Errorf("checkpoint not found: %s", checkpoint)
		}
		env = weights.EnvMap(m, variant)
	case envBool("FLASHCLI_SKIP_WEIGHTS"):
		env = weights.EnvMap(m, variant)
	default:
		checkpoint, env, err = weights.PrepareBundle(ctx, m, ver, variant, quiet, false)
		if err != nil {
			return "", nil, nil, err
		}
	}
	_ = mainSpec
	extra := map[string]string{}
	for key, ex := range extraSpecs {
		extra[key] = weights.ExtraWeightDest(checkpoint, abs, key, ex)
	}
	return checkpoint, extra, env, nil
}

// StartNativeExec starts a native-exec worker for a prepared bundle.
func StartNativeExec(ctx context.Context, p Prepared, capability string, args []string) (*nativeexec.Process, error) {
	if p.Manifest == nil {
		return nil, errors.New("prepared manifest is nil")
	}
	entry := p.Manifest.EntryFor(capability, p.Variant)
	if entry == nil || entry.Kind != "native-exec" {
		return nil, fmt.Errorf("bundle %q does not have a native-exec %s entry", p.Manifest.Name, capability)
	}
	spec, err := nativeexec.SpecFromEntry(entry)
	if err != nil {
		return nil, err
	}
	_, rel, err := resolveRuntimeRel(p.Manifest)
	if err != nil {
		return nil, err
	}
	opts := mergeOptions(optionDefaults(p.Manifest, capability, p.Variant), parseFlags(args))
	tokenizer := strings.TrimSpace(os.Getenv("FLASH_RT_PALIGEMMA_TOKENIZER"))
	if tokenizer == "" {
		tokenizer = postpull.DefaultPaligemmaPath()
	}
	ph := nativeexec.Placeholders{
		Checkpoint: p.Checkpoint,
		BundleRoot: p.BundleRoot,
		ModelsDir:  paths.Models(),
		Preset:     p.Manifest.Name,
		Variant:    p.Variant,
		RuntimeDir: filepath.Join(p.BundleRoot, filepath.FromSlash(rel)),
		Tokenizer:  tokenizer,
		Extra:      p.Extra,
		Options:    opts,
	}
	return nativeexec.Start(ctx, spec, ph, p.Env)
}

func resolveRuntimeRel(m *manifest.Manifest) (string, string, error) {
	key := ResolveEnvKey(m)
	if key == "" {
		return "", "", fmt.Errorf("bundle has no matching runtime env key; set FLASHCLI_RUNTIME_ENV_KEY")
	}
	rel, ok := m.RuntimeMap()[key]
	if !ok {
		return "", "", fmt.Errorf("runtime key %q not found", key)
	}
	return key, rel, nil
}

func optionDefaults(m *manifest.Manifest, capability, variant string) map[string]string {
	key := capability + "_options"
	var raw any = m.Raw[key]
	if variant != "" {
		if variants, ok := m.Raw["variants"].(map[string]any); ok {
			if block, ok := variants[variant].(map[string]any); ok {
				if v, ok := block[key]; ok {
					raw = v
				}
			}
		}
	}
	out := map[string]string{}
	items, _ := raw.([]any)
	for _, it := range items {
		obj, _ := it.(map[string]any)
		name, _ := obj["name"].(string)
		if name == "" {
			continue
		}
		if def, ok := obj["default"]; ok {
			out[name] = fmt.Sprintf("%v", def)
		}
	}
	return out
}

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

func mergeOptions(defaults map[string]string, parsed map[string]any) map[string]string {
	out := make(map[string]string, len(defaults)+len(parsed))
	for k, v := range defaults {
		out[k] = v
	}
	for k, v := range parsed {
		out[k] = fmt.Sprintf("%v", v)
	}
	return out
}

var hostFlagNames = map[string]bool{
	"--checkpoint": true, "--mtp-checkpoint": true, "--quiet": true, "-q": true,
	"--no-auto-install": true, "-h": true, "--help": true,
}

func mapEnv(env map[string]string) []string {
	out := make([]string, 0, len(env))
	for k, v := range env {
		out = append(out, k+"="+v)
	}
	sort.Strings(out)
	return out
}
