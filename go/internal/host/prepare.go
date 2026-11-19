package host

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

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
