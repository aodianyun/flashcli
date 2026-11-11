package host

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/ref"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// RefPaths returns the existing cache paths owned by a ref. includeData adds
// the bundle tree and unshared weights; runtime directories are always
// included when they can be resolved. It is the shared implementation for
// `flashcli bundle clean` and the server's model cleanup.
func RefPaths(refArg string, includeData bool) []string {
	refArg = strings.TrimSpace(refArg)
	if refArg == "" {
		return nil
	}
	markers := Markers()
	targets, others := splitMarkers(markers, refArg)
	if len(targets) == 0 {
		if !includeData {
			return RuntimePathsForRef(refArg)
		}
		key, ok := canonicalCacheKey(refArg)
		if !ok {
			return nil
		}
		out := []string{
			filepath.Join(paths.Bundles(), filepath.FromSlash(key)),
			filepath.Join(paths.Models(), filepath.FromSlash(key)),
		}
		out = append(out, RuntimePathsForRef(refArg)...)
		return existingCachePaths(out)
	}

	sharedBundles, sharedWeights, sharedRuntimes := sharedCacheKeys(others)
	rtIndex := readRuntimeIndex()
	var out []string
	foundRuntime := false
	for _, marker := range targets {
		key := stringValue(marker["cache_key"])
		if key == "" {
			continue
		}
		bundleRoot := stringValue(marker["bundle_root"])
		if includeData {
			if !sharedBundles[key] {
				out = append(out, filepath.Join(paths.Bundles(), filepath.FromSlash(key)))
			}
			weightsKey := markerWeightsKey(marker, key, bundleRoot)
			if weightsKey != "" && !sharedWeights[weightsKey] {
				out = append(out, filepath.Join(paths.Models(), filepath.FromSlash(weightsKey)))
			}
		}
		if runtimeID := markerRuntimeID(marker, rtIndex); runtimeID != "" {
			foundRuntime = true
			if !sharedRuntimes[runtimeID] {
				out = append(out, runtime.Dir(runtimeID))
			}
		}
	}
	if !foundRuntime {
		out = append(out, RuntimePathsForRef(refArg)...)
	}
	return existingCachePaths(out)
}

// RuntimePathsForRef resolves the runtime directories associated with ref,
// including the preset-marker fallback used by older caches.
func RuntimePathsForRef(refArg string) []string {
	refArg = strings.TrimSpace(refArg)
	if refArg == "" {
		return nil
	}
	markers := Markers()
	targets, others := splitMarkers(markers, refArg)
	_, _, sharedRuntimes := sharedCacheKeys(others)
	rtIndex := readRuntimeIndex()
	var out []string
	for _, marker := range targets {
		if runtimeID := markerRuntimeID(marker, rtIndex); runtimeID != "" && !sharedRuntimes[runtimeID] {
			out = append(out, runtime.Dir(runtimeID))
		}
	}
	if len(out) == 0 {
		if runtimeID, ok := findRuntimeForRef(refArg); ok && !sharedRuntimes[runtimeID] {
			out = append(out, runtime.Dir(runtimeID))
		}
	}
	return existingCachePaths(out)
}

// RuntimePaths returns every runtime directory.
func RuntimePaths() []string {
	entries, _ := os.ReadDir(paths.Runtimes())
	out := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			out = append(out, runtime.Dir(entry.Name()))
		}
	}
	return out
}

// AllDataPaths returns the bundle, weights, and runtime roots.
func AllDataPaths() []string {
	return []string{paths.Runtimes(), paths.Models(), paths.Bundles()}
}

// OrphanPaths returns stale bundle/model entries whose bundle_root is gone,
// plus runtime directories with no marker or no usable bundle root.
func OrphanPaths() []string {
	seen := map[string]bool{}
	out := make([]string, 0)
	add := func(path string) {
		if path != "" && !seen[path] {
			seen[path] = true
			out = append(out, path)
		}
	}

	markers := Markers()
	for _, marker := range markers {
		if bundleRootUsable(stringValue(marker["bundle_root"])) {
			continue
		}
		key := stringValue(marker["cache_key"])
		if key == "" {
			continue
		}
		weightsKey := markerWeightsKey(marker, key, stringValue(marker["bundle_root"]))
		add(filepath.Join(paths.Bundles(), filepath.FromSlash(key)))
		if !storeKeyUsedByOtherMarkers(markers, weightsKey, key) {
			add(filepath.Join(paths.Models(), filepath.FromSlash(weightsKey)))
		}
		if runtimeID := stringValue(marker["runtime_id"]); runtimeID != "" {
			add(runtime.Dir(runtimeID))
		}
	}

	entries, _ := os.ReadDir(paths.Runtimes())
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		dir := runtime.Dir(entry.Name())
		if seen[dir] {
			continue
		}
		marker := runtime.ReadMarker(entry.Name())
		if len(marker) == 0 {
			add(dir)
			continue
		}
		root := stringValue(marker["bundle_root"])
		if root == "" {
			root = stringValue(marker["local_root"])
		}
		if !bundleRootUsable(root) {
			add(dir)
		}
	}
	return existingCachePaths(out)
}

// Markers returns every cached bundle marker with cache_key populated.
func Markers() []map[string]any {
	markers, _ := readMarkers()
	return markers
}

func splitMarkers(markers []map[string]any, refArg string) (targets, others []map[string]any) {
	targetKey := ""
	if p, err := ref.Parse(refArg); err == nil {
		targetKey = refCacheKey(p)
	}
	for _, marker := range markers {
		name := stringValue(marker["ref"])
		key := stringValue(marker["cache_key"])
		if name == refArg || key == refArg || (targetKey != "" && key == targetKey) {
			targets = append(targets, marker)
		} else {
			others = append(others, marker)
		}
	}
	return targets, others
}

func sharedCacheKeys(others []map[string]any) (bundles, modelWeights, runtimes map[string]bool) {
	bundles = map[string]bool{}
	modelWeights = map[string]bool{}
	runtimes = map[string]bool{}
	rtIndex := readRuntimeIndex()
	for _, marker := range others {
		key := stringValue(marker["cache_key"])
		if key != "" {
			bundles[key] = true
		}
		if weightsKey := markerWeightsKey(marker, key, stringValue(marker["bundle_root"])); weightsKey != "" {
			modelWeights[weightsKey] = true
		}
		if runtimeID := markerRuntimeID(marker, rtIndex); runtimeID != "" {
			runtimes[runtimeID] = true
		}
	}
	return bundles, modelWeights, runtimes
}

func canonicalCacheKey(refArg string) (string, bool) {
	p, err := ref.Parse(refArg)
	if err != nil {
		return "", false
	}
	return refCacheKey(p), true
}

// refCacheKey mirrors the CLI/protocol cache key for a parsed ref.
func refCacheKey(p ref.Parsed) string {
	version := p.Version
	if p.Local || version == "" {
		version = "local"
	}
	return weights.TreeKey(p.Name, version)
}

func storeKeyUsedByOtherMarkers(markers []map[string]any, weightsKey, currentBundleKey string) bool {
	if weightsKey == "" {
		return false
	}
	for _, marker := range markers {
		key := stringValue(marker["cache_key"])
		if key == currentBundleKey {
			continue
		}
		if markerWeightsKey(marker, key, stringValue(marker["bundle_root"])) == weightsKey {
			return true
		}
	}
	return false
}

func findRuntimeForRef(refArg string) (string, bool) {
	p, err := ref.Parse(refArg)
	if err != nil {
		return "", false
	}
	root := paths.Runtimes()
	entries, err := os.ReadDir(root)
	if err == nil {
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			marker := runtime.ReadMarker(entry.Name())
			if len(marker) == 0 {
				continue
			}
			if preset := stringValue(marker["preset"]); preset == p.Name {
				return entry.Name(), true
			}
			localRoot := stringValue(marker["local_root"])
			if localRoot != "" && p.Local &&
				strings.HasSuffix(filepath.Clean(localRoot), filepath.Clean(p.Name)) {
				return entry.Name(), true
			}
		}
	}
	// Fallback: the bundle sync marker records the runtime id even when the
	// runtime marker is missing (older cache or an aborted run).
	if marker := runtime.ReadPresetMarker(refCacheKey(p)); marker != nil {
		if runtimeID := stringValue(marker["runtime_id"]); runtimeID != "" {
			if _, err := os.Stat(runtime.Dir(runtimeID)); err == nil {
				return runtimeID, true
			}
		}
	}
	return "", false
}

func existingCachePaths(paths []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(paths))
	for _, path := range paths {
		if path == "" || seen[path] {
			continue
		}
		seen[path] = true
		if _, err := os.Stat(path); err == nil {
			out = append(out, path)
		}
	}
	return out
}
