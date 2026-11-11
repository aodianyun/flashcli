package host

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

// RemoveResult reports what was removed for one model reference.
type RemoveResult struct {
	Ref           string `json:"ref"`
	Removed       bool   `json:"removed"`
	FreedBytes    int64  `json:"freed_bytes"`
	SharedBundle  bool   `json:"shared_bundle,omitempty"`
	SharedWeights bool   `json:"shared_weights,omitempty"`
}

// RemoveCachedRef deletes the cached bundle/weights for every marker of ref.
// The original bundle source (for local dev bundles) is never touched; only the
// canonical cache directories under FLASHCLI_HOME are removed. Shared weights
// or bundle trees used by another cached ref are kept.
func RemoveCachedRef(ref string) (RemoveResult, error) {
	ref = strings.TrimSpace(ref)
	if ref == "" {
		return RemoveResult{}, fmt.Errorf("ref is required")
	}
	targets, others := splitMarkers(Markers(), ref)
	if len(targets) == 0 {
		return RemoveResult{}, fmt.Errorf("model %q is not cached", ref)
	}

	bundlesRoot := paths.Bundles()
	sharedBundles, sharedWeights, _ := sharedCacheKeys(others)
	res := RemoveResult{Ref: ref, Removed: true}
	for _, marker := range targets {
		key := stringValue(marker["cache_key"])
		if key == "" {
			continue
		}
		bundleDir := filepath.Join(bundlesRoot, filepath.FromSlash(key))
		if sharedBundles[key] {
			res.SharedBundle = true
			if safeUnder(bundlesRoot, bundleDir) {
				_ = os.Remove(filepath.Join(bundleDir, flashhub.MarkerName))
			}
		}
		weightsKey := markerWeightsKey(marker, key, stringValue(marker["bundle_root"]))
		if weightsKey != "" && sharedWeights[weightsKey] {
			res.SharedWeights = true
		}
	}

	freed, err := RemovePaths(RefPaths(ref, true))
	if err != nil {
		return res, err
	}
	res.FreedBytes = freed
	return res, nil
}

// safeUnder reports whether path stays inside root after cleaning.
func safeUnder(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	if err != nil || filepath.IsAbs(rel) {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(os.PathSeparator))
}
