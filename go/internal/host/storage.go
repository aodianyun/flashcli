package host

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

// SharedCacheTargets are the user-facing shared cache cleanup targets. Model
// runtimes are intentionally excluded: they are cleaned by bundle/model
// cleanup (host.RemoveCachedRef / flashcli bundle clean).
func SharedCacheTargets() []string {
	return []string{"cache"}
}

// SharedCachePaths returns the filesystem roots removed by a logical target.
// `cache` groups re-downloadable tooling: download cache, base Python, and uv.
// Model runtimes are not part of this group.
func SharedCachePaths(name string) ([]string, bool) {
	switch strings.TrimSpace(name) {
	case "cache":
		return []string{
			filepath.Join(paths.Home(), "cache"),
			filepath.Join(paths.Home(), "python"),
			filepath.Join(paths.Home(), "tools"),
		}, true
	// Legacy API targets kept for compatibility with older clients.
	case "python":
		return []string{filepath.Join(paths.Home(), "python")}, true
	case "tools":
		return []string{filepath.Join(paths.Home(), "tools")}, true
	}
	return nil, false
}

// CleanSharedCaches removes the selected shared storage areas and returns the
// unique bytes freed. Model bundles/weights are not touched; use
// RemoveCachedRef for those.
func CleanSharedCaches(targets []string) (int64, error) {
	seenTarget := map[string]bool{}
	seenPath := map[string]bool{}
	var pathsToRemove []string
	for _, target := range targets {
		target = strings.TrimSpace(target)
		if target == "" {
			continue
		}
		if seenTarget[target] {
			continue
		}
		targetPaths, ok := SharedCachePaths(target)
		if !ok {
			return 0, fmt.Errorf("unknown cache target %q", target)
		}
		seenTarget[target] = true
		for _, path := range targetPaths {
			if !seenPath[path] {
				seenPath[path] = true
				pathsToRemove = append(pathsToRemove, path)
			}
		}
	}
	if len(pathsToRemove) == 0 {
		return 0, fmt.Errorf("targets is required")
	}
	return RemovePaths(pathsToRemove)
}

// RemovePaths removes cache paths under FLASHCLI_HOME and returns the unique
// bytes freed. Both flashcli and flashserver use this for cleanup.
func RemovePaths(pathsToRemove []string) (int64, error) {
	before := storageTotal()
	for _, path := range pathsToRemove {
		if !safeUnder(paths.Home(), path) {
			return 0, fmt.Errorf("refusing to remove %s", path)
		}
		if err := os.RemoveAll(path); err != nil {
			return 0, err
		}
	}
	freed := before - storageTotal()
	if freed < 0 {
		freed = 0
	}
	return freed, nil
}

func storageTotal() int64 {
	var total int64
	for _, area := range Storage() {
		total += area.Bytes
	}
	return total
}
