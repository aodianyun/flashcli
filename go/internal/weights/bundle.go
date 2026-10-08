package weights

import (
	"context"
	"fmt"
	"path/filepath"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/postpull"
)

// HasSource reports whether a spec declares any downloadable source.
func (s Spec) HasSource() bool {
	return s.Repo != "" || s.URL != "" || s.RelativeDir != ""
}

// ManifestSpecs resolves the main weights spec and extra_weights for a variant.
// weightsRel is the checkpoint-relative subdirectory ("checkpoint" by default).
func ManifestSpecs(m *manifest.Manifest, variant string) (Spec, string, map[string]Spec, error) {
	variants := variantBlocks(m)
	if len(variants) > 0 {
		key := strings.TrimSpace(variant)
		if key == "" {
			keys := make([]string, 0, len(variants))
			for k := range variants {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			return Spec{}, "", nil, fmt.Errorf("Bundle %q has variants; add @variant (choose from: %s)", m.Name, strings.Join(keys, ", "))
		}
		block, ok := variants[key]
		if !ok {
			keys := make([]string, 0, len(variants))
			for k := range variants {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			return Spec{}, "", nil, fmt.Errorf("Unknown model variant %q for bundle %q; choose from: %s", key, m.Name, strings.Join(keys, ", "))
		}
		rel := "checkpoint/" + key
		if r := strings.TrimSpace(str(block["weights_dir"])); r != "" {
			rel = strings.Trim(r, "/")
		}
		main := SpecFromMap(asStringMap(block["weights"]))
		extra := map[string]Spec{}
		for k, v := range asStringMap(block["extra_weights"]) {
			if sub, ok := v.(map[string]any); ok {
				extra[k] = SpecFromMap(sub)
			}
		}
		return main, rel, extra, nil
	}

	rel := "checkpoint"
	if r := strings.TrimSpace(str(m.Raw["weights_dir"])); r != "" {
		rel = strings.Trim(r, "/")
	}
	main := SpecFromMap(asStringMap(m.Raw["weights"]))
	extra := map[string]Spec{}
	for k, v := range asStringMap(m.Raw["extra_weights"]) {
		if sub, ok := v.(map[string]any); ok {
			extra[k] = SpecFromMap(sub)
		}
	}
	return main, rel, extra, nil
}

// DownloadBundle fetches a bundle's main + extra weights into the cache.
// version feeds the cache key; use "local" for a bare local directory.
func DownloadBundle(ctx context.Context, m *manifest.Manifest, version, variant string, quiet bool) (string, error) {
	main, rel, extra, err := ManifestSpecs(m, variant)
	if err != nil {
		return "", err
	}
	cacheDir := filepath.Join(paths.Models(), filepath.FromSlash(CacheKey(m.Name, version, variant)))
	checkpoint := filepath.Join(cacheDir, filepath.FromSlash(rel))

	if main.HasSource() {
		if err := Download(ctx, main, checkpoint, quiet); err != nil {
			return "", err
		}
	}
	for key, spec := range extra {
		spec.Raw["_bundle_root"] = m.Root
		dest := ExtraWeightDest(checkpoint, m.Root, key, spec)
		if dest == "" {
			return "", fmt.Errorf("extra_weights.%s: cannot resolve destination", key)
		}
		if err := Download(ctx, spec, dest, quiet); err != nil {
			return "", err
		}
	}
	if err := WriteMarker(cacheDir, m.Name, checkpoint); err != nil {
		return "", err
	}
	return checkpoint, nil
}

// EnvMap returns manifest “env“ (variant-aware) with placeholders expanded.
func EnvMap(m *manifest.Manifest, variant string) map[string]string {
	var block map[string]any
	if variants := variantBlocks(m); len(variants) > 0 {
		if b, ok := variants[variant]; ok {
			block = asStringMap(b["env"])
		}
	} else {
		block = asStringMap(m.Raw["env"])
	}
	out := map[string]string{}
	for k, v := range block {
		s, ok := v.(string)
		if !ok {
			continue
		}
		s = strings.ReplaceAll(s, "{models_dir}", paths.Models())
		s = strings.ReplaceAll(s, "{bundle_root}", m.Root)
		out[k] = s
	}
	return out
}

// PrepareBundle downloads main + extra_weights + extra_pull, runs post_pull, and
// returns the checkpoint plus the manifest/post-pull env to pass to the entry.
func PrepareBundle(ctx context.Context, m *manifest.Manifest, version, variant string, quiet bool) (string, map[string]string, error) {
	checkpoint, err := DownloadBundle(ctx, m, version, variant, quiet)
	if err != nil {
		return "", nil, err
	}
	if extraPull, ok := m.Raw["extra_pull"].(map[string]any); ok {
		for key, v := range extraPull {
			specMap, ok := v.(map[string]any)
			if !ok {
				continue
			}
			spec := SpecFromMap(specMap)
			if !spec.HasSource() {
				continue
			}
			name := spec.CacheName
			if name == "" {
				name = key
			}
			dest := filepath.Join(paths.Models(), name)
			if err := Download(ctx, spec, dest, quiet); err != nil {
				return "", nil, err
			}
		}
	}
	env := EnvMap(m, variant)
	steps, _ := m.Raw["post_pull"].([]any)
	postEnv, err := postpull.Run(ctx, steps, quiet)
	if err != nil {
		return "", nil, err
	}
	for _, kv := range postEnv {
		if i := strings.IndexByte(kv, '='); i > 0 {
			env[kv[:i]] = kv[i+1:]
		}
	}
	return checkpoint, env, nil
}

func variantBlocks(m *manifest.Manifest) map[string]map[string]any {
	raw, ok := m.Raw["variants"].(map[string]any)
	if !ok {
		return nil
	}
	out := map[string]map[string]any{}
	for k, v := range raw {
		if block, ok := v.(map[string]any); ok {
			out[k] = block
		}
	}
	return out
}

func asStringMap(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}
