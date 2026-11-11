package host

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
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
	markers, err := readMarkers()
	if err != nil {
		return RemoveResult{}, err
	}
	var targets, others []map[string]any
	for _, marker := range markers {
		name := stringValue(marker["ref"])
		key := stringValue(marker["cache_key"])
		if name == ref || (name == "" && key == ref) {
			targets = append(targets, marker)
		} else {
			others = append(others, marker)
		}
	}
	if len(targets) == 0 {
		return RemoveResult{}, fmt.Errorf("model %q is not cached", ref)
	}

	bundlesRoot := paths.Bundles()
	modelsRoot := paths.Models()
	runtimes := readRuntimeIndex()
	sharedBundles := map[string]bool{}
	sharedWeights := map[string]bool{}
	sharedRuntimes := map[string]bool{}
	for _, marker := range others {
		key := stringValue(marker["cache_key"])
		sharedBundles[key] = true
		wk := markerWeightsKey(marker, key, stringValue(marker["bundle_root"]))
		if wk != "" {
			sharedWeights[wk] = true
		}
		if rid := markerRuntimeID(marker, runtimes); rid != "" {
			sharedRuntimes[rid] = true
		}
	}

	res := RemoveResult{Ref: ref, Removed: true}
	seenBundles := map[string]bool{}
	seenWeights := map[string]bool{}
	seenRuntimes := map[string]bool{}
	for _, marker := range targets {
		key := stringValue(marker["cache_key"])
		if key == "" {
			continue
		}
		bundleRoot := stringValue(marker["bundle_root"])
		weightsKey := markerWeightsKey(marker, key, bundleRoot)
		bundleDir := filepath.Join(bundlesRoot, filepath.FromSlash(key))
		markerPath := filepath.Join(bundleDir, flashhub.MarkerName)

		if !seenBundles[key] {
			seenBundles[key] = true
			if safeUnder(bundlesRoot, bundleDir) {
				if sharedBundles[key] {
					res.SharedBundle = true
					_ = os.Remove(markerPath)
				} else {
					res.FreedBytes += dirSize(bundleDir)
					if err := os.RemoveAll(bundleDir); err != nil {
						return res, err
					}
				}
			}
		}

		if weightsKey != "" && !seenWeights[weightsKey] {
			seenWeights[weightsKey] = true
			weightsDir := filepath.Join(modelsRoot, filepath.FromSlash(weightsKey))
			if safeUnder(modelsRoot, weightsDir) {
				if sharedWeights[weightsKey] {
					res.SharedWeights = true
				} else {
					res.FreedBytes += dirSize(weightsDir)
					if err := os.RemoveAll(weightsDir); err != nil {
						return res, err
					}
				}
			}
		}

		runtimeID := markerRuntimeID(marker, runtimes)
		if runtimeID == "" || seenRuntimes[runtimeID] {
			continue
		}
		seenRuntimes[runtimeID] = true
		if sharedRuntimes[runtimeID] {
			continue
		}
		runtimeDir := runtime.Dir(runtimeID)
		if !safeUnder(paths.Runtimes(), runtimeDir) {
			continue
		}
		res.FreedBytes += dirUsage(runtimeDir, map[fileKey]bool{})
		if err := os.RemoveAll(runtimeDir); err != nil {
			return res, err
		}
	}
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
