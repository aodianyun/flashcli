// Package host contains model-agnostic host services shared by the CLI and
// flashserver. It intentionally does not import the CLI presentation layer.
package host

import (
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/manifest"
	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/runtime"
	"github.com/aodianyun/flashcli/go/internal/weights"
)

// Model is a locally cached bundle/model view for the HTTP API.
type Model struct {
	Ref           string `json:"ref"`
	CacheKey      string `json:"cache_key"`
	Variant       string `json:"variant,omitempty"`
	BundleCached  bool   `json:"bundle_cached"`
	WeightsCached bool   `json:"weights_cached"`
	Serve         bool   `json:"serve"`
	BundleBytes   int64  `json:"bundle_bytes"`
	RuntimeID     string `json:"runtime_id,omitempty"`
	RuntimeBytes  int64  `json:"runtime_bytes"`
	WeightsBytes  int64  `json:"weights_bytes"`
	WeightsKey    string `json:"weights_key,omitempty"`
	Directory     string `json:"directory"`
	WeightsSource string `json:"weights_source,omitempty"`
	WeightsRepo   string `json:"weights_repo,omitempty"`
	WeightsRev    string `json:"weights_revision,omitempty"`
}

// Area is one cache area for /v1/storage.
type Area struct {
	Name  string `json:"name"`
	Path  string `json:"path"`
	Bytes int64  `json:"bytes"`
}

// ListModels returns locally cached bundle/model entries with readiness and
// serve capability. The public FlashHub catalog is served separately by the
// server's /v1/catalog proxy.
func ListModels() ([]Model, error) {
	markers, err := readMarkers()
	if err != nil {
		return nil, err
	}
	runtimes := readRuntimeIndex()
	out := make([]Model, 0, len(markers))
	for _, marker := range markers {
		key := stringValue(marker["cache_key"])
		if key == "" {
			continue
		}
		ref := stringValue(marker["ref"])
		if ref == "" {
			ref = key
		}
		variant := stringValue(marker["variant"])
		bundleRoot := stringValue(marker["bundle_root"])
		bundleOK := bundleRootUsable(bundleRoot)
		weightsKey := markerWeightsKey(marker, key, bundleRoot)
		weightsOK, source, repo, rev := weightsInfo(weightsKey, bundleRoot, variant)
		runtimeID := markerRuntimeID(marker, runtimes)
		out = append(out, Model{
			Ref:           ref,
			CacheKey:      key,
			Variant:       variant,
			BundleCached:  bundleOK,
			WeightsCached: weightsOK,
			Serve:         bundleOK && bundleServes(bundleRoot),
			BundleBytes:   dirSize(filepath.Join(paths.Bundles(), filepath.FromSlash(key))),
			RuntimeID:     runtimeID,
			RuntimeBytes:  runtimeSize(runtimeID),
			WeightsBytes:  dirSize(filepath.Join(paths.Models(), filepath.FromSlash(weightsKey))),
			WeightsKey:    weightsKey,
			Directory:     filepath.ToSlash(filepath.Join(paths.Home(), "{bundles,models}", weightsKey)),
			WeightsSource: source,
			WeightsRepo:   repo,
			WeightsRev:    rev,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CacheKey < out[j].CacheKey })
	return out, nil
}

// runtimeIndex maps cached bundles back to their per-bundle runtime directory.
// Newer bundle markers already contain runtime_id; the index is a fallback for
// markers written before that field was added.
type runtimeIndex struct {
	byBundleRoot map[string]string
	byRepoURL    map[string]string
}

func readRuntimeIndex() runtimeIndex {
	idx := runtimeIndex{byBundleRoot: map[string]string{}, byRepoURL: map[string]string{}}
	entries, err := os.ReadDir(paths.Runtimes())
	if err != nil {
		return idx
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		id := entry.Name()
		marker := runtime.ReadMarker(id)
		if marker == nil {
			continue
		}
		if root := stringValue(marker["bundle_root"]); root != "" {
			idx.byBundleRoot[root] = id
		}
		if repo := stringValue(marker["repo_url"]); repo != "" {
			idx.byRepoURL[repo] = id
		}
	}
	return idx
}

func markerRuntimeID(marker map[string]any, idx runtimeIndex) string {
	if id := stringValue(marker["runtime_id"]); id != "" {
		return id
	}
	if id := idx.byBundleRoot[stringValue(marker["bundle_root"])]; id != "" {
		return id
	}
	if id := idx.byRepoURL[stringValue(marker["repo_url"])]; id != "" {
		return id
	}
	bundleRoot := stringValue(marker["bundle_root"])
	if !bundleRootUsable(bundleRoot) {
		return ""
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil {
		return ""
	}
	if repo := stringValue(marker["repo_url"]); repo != "" {
		return runtime.IDFromRepo(repo, m.Name)
	}
	return runtime.IDFromPath(bundleRoot, m.Name)
}

func runtimeSize(runtimeID string) int64 {
	if runtimeID == "" {
		return 0
	}
	return dirUsage(runtime.Dir(runtimeID), map[fileKey]bool{})
}

// Storage returns unique allocated disk usage for the local cache areas.
// Hardlinked files are counted once across all areas.
func Storage() []Area {
	items := []struct {
		name string
		path string
	}{
		{"bundles", paths.Bundles()},
		{"models", paths.Models()},
		{"runtimes", paths.Runtimes()},
		{"cache", filepath.Join(paths.Home(), "cache")},
		{"tools", filepath.Join(paths.Home(), "tools")},
		{"python", filepath.Join(paths.Home(), "python")},
	}
	out := make([]Area, 0, len(items))
	seen := map[fileKey]bool{}
	for _, item := range items {
		out = append(out, Area{Name: item.name, Path: filepath.ToSlash(item.path), Bytes: dirUsage(item.path, seen)})
	}
	return out
}

func readMarkers() ([]map[string]any, error) {
	root := paths.Bundles()
	var out []map[string]any
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		if d.IsDir() || d.Name() != flashhub.MarkerName {
			return nil
		}
		blob, err := os.ReadFile(path)
		if err != nil {
			return nil
		}
		var marker map[string]any
		if json.Unmarshal(blob, &marker) != nil {
			return nil
		}
		rel, err := filepath.Rel(root, filepath.Dir(path))
		if err == nil {
			marker["cache_key"] = filepath.ToSlash(rel)
		}
		out = append(out, marker)
		return nil
	})
	return out, err
}

func bundleRootUsable(root string) bool {
	if strings.TrimSpace(root) == "" {
		return false
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return false
	}
	_, err = manifest.Load(root)
	return err == nil
}

// BundleRootUsable reports whether root contains a loadable bundle manifest.
func BundleRootUsable(root string) bool {
	return bundleRootUsable(root)
}

// MarkerWeightsKey resolves the shared source/repo@revision store key for a
// cached bundle marker.
func MarkerWeightsKey(marker map[string]any, fallback, bundleRoot string) string {
	return markerWeightsKey(marker, fallback, bundleRoot)
}

// bundleServes reports whether the bundle declares a serve entry, either at the
// top level or in one of its environment variants.
func bundleServes(root string) bool {
	if strings.TrimSpace(root) == "" {
		return false
	}
	blob, err := os.ReadFile(filepath.Join(root, flashhub.ManifestPath))
	if err != nil {
		return false
	}
	var doc struct {
		Entry    map[string]json.RawMessage `json:"entry"`
		Defaults struct {
			Entry map[string]json.RawMessage `json:"entry"`
		} `json:"defaults"`
		Environments map[string]struct {
			Entry map[string]json.RawMessage `json:"entry"`
		} `json:"environments"`
	}
	if json.Unmarshal(blob, &doc) != nil {
		return false
	}
	if _, ok := doc.Entry["serve"]; ok {
		return true
	}
	if _, ok := doc.Defaults.Entry["serve"]; ok {
		return true
	}
	for _, env := range doc.Environments {
		if _, ok := env.Entry["serve"]; ok {
			return true
		}
	}
	return false
}

func markerWeightsKey(marker map[string]any, fallback, bundleRoot string) string {
	if key := stringValue(marker["weights_key"]); key != "" {
		return key
	}
	if !bundleRootUsable(bundleRoot) {
		return fallback
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil || m.FormatVersion < 4 {
		return fallback
	}
	return weights.StoreKeyFor(m, "")
}

func weightsInfo(weightsKey, bundleRoot, variant string) (bool, string, string, string) {
	if !bundleRootUsable(bundleRoot) {
		return false, "", "", ""
	}
	m, err := manifest.Load(bundleRoot)
	if err != nil {
		return false, "", "", ""
	}
	return WeightsInfo(m, weightsKey, variant)
}

// WeightsInfo reports whether a bundle's weights are ready in the shared store
// and returns their source/repo/revision. Both the CLI and flashserver use this
// function so cache readiness cannot diverge.
func WeightsInfo(m *manifest.Manifest, weightsKey, variant string) (bool, string, string, string) {
	if m == nil {
		return false, "", "", ""
	}
	spec, rel, _, err := weights.ManifestSpecs(m, variant)
	if err != nil {
		if variant == "" {
			return markerCached(filepath.Join(paths.Models(), filepath.FromSlash(weightsKey), "checkpoint")), "", "", ""
		}
		return false, "", "", ""
	}
	if rel == "" && m.FormatVersion < 4 {
		rel = "checkpoint"
	}
	dir := filepath.Join(paths.Models(), filepath.FromSlash(weightsKey), filepath.FromSlash(rel))
	if weights.IsCached(dir, spec) {
		return true, spec.Source, spec.Repo, spec.Revision
	}
	return false, spec.Source, spec.Repo, spec.Revision
}

// WeightsCachedForMarker reports weights readiness for a cached bundle marker.
func WeightsCachedForMarker(marker map[string]any, fallbackKey string) bool {
	key := stringValue(marker["cache_key"])
	if key == "" {
		key = fallbackKey
	}
	bundleRoot := stringValue(marker["bundle_root"])
	weightsKey := markerWeightsKey(marker, key, bundleRoot)
	cached, _, _, _ := weightsInfo(weightsKey, bundleRoot, stringValue(marker["variant"]))
	return cached
}

func markerCached(dir string) bool {
	if _, err := os.Stat(filepath.Join(dir, ".flashcli_download.incomplete")); err == nil {
		return false
	}
	cp, ok := weights.ReadMarker(dir)
	if !ok {
		return false
	}
	info, err := os.Stat(cp)
	return err == nil && info.IsDir()
}

func dirSize(root string) int64 {
	var total int64
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if info, err := d.Info(); err == nil {
			total += info.Size()
		}
		return nil
	})
	return total
}

type fileKey struct {
	dev uint64
	ino uint64
}

// dirUsage sums allocated bytes while counting each inode only once. Hardlinked
// files (uv cache <-> runtimes) would otherwise be double-counted across areas.
func dirUsage(root string, seen map[fileKey]bool) int64 {
	var total int64
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		if key, ok := fileKeyFor(info); ok {
			if seen[key] {
				return nil
			}
			seen[key] = true
		}
		total += allocatedBytes(info)
		return nil
	})
	return total
}

func stringValue(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
