package host

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

// shared cache targets that the UI may remove.
var sharedCacheTargets = map[string]func() string{
	"cache":    func() string { return filepath.Join(paths.Home(), "cache") },
	"python":   func() string { return filepath.Join(paths.Home(), "python") },
	"tools":    func() string { return filepath.Join(paths.Home(), "tools") },
	"runtimes": paths.Runtimes,
}

// CleanSharedCaches removes the selected shared caches and returns the unique
// bytes freed. Model bundles/weights are not touched; use RemoveCachedRef.
func CleanSharedCaches(targets []string) (int64, error) {
	seen := map[string]bool{}
	var pathsToRemove []string
	for _, target := range targets {
		target = strings.TrimSpace(target)
		if target == "" {
			continue
		}
		pathFor, ok := sharedCacheTargets[target]
		if !ok {
			return 0, fmt.Errorf("unknown cache target %q", target)
		}
		if seen[target] {
			continue
		}
		seen[target] = true
		pathsToRemove = append(pathsToRemove, pathFor())
	}
	if len(pathsToRemove) == 0 {
		return 0, fmt.Errorf("targets is required")
	}
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
