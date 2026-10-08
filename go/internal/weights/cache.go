package weights

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

var cacheSegmentRe = regexp.MustCompile(`[^\w.\-+]+`)

// CacheKey returns "bundle/version" or "bundle/version@variant".
func CacheKey(bundle, version, variant string) string {
	b := cacheSegment(bundle)
	v := cacheSegment(version)
	if variant != "" {
		return b + "/" + v + "@" + cacheSegment(variant)
	}
	return b + "/" + v
}

func cacheSegment(s string) string {
	return cacheSegmentRe.ReplaceAllString(strings.TrimSpace(s), "-")
}

// CheckpointDir returns the default checkpoint directory for a preset.
func CheckpointDir(bundle, version, variant string) string {
	return filepath.Join(paths.Models(), filepath.FromSlash(CacheKey(bundle, version, variant)), "checkpoint")
}

// ExtraWeightDest mirrors Python extra_weight_dest (checkpoint_subdir > relative_dir > cache_name/key).
func ExtraWeightDest(checkpointDir, bundleRoot, key string, spec Spec) string {
	if spec.CheckpointSubdir != "" {
		if checkpointDir == "" {
			return ""
		}
		return filepath.Join(checkpointDir, filepath.FromSlash(spec.CheckpointSubdir))
	}
	if bundleRoot != "" && spec.RelativeDir != "" {
		return filepath.Join(bundleRoot, filepath.FromSlash(spec.RelativeDir))
	}
	name := spec.CacheName
	if name == "" {
		name = key
	}
	return filepath.Join(paths.Models(), name)
}

type markerData struct {
	Preset     string `json:"preset"`
	Checkpoint string `json:"checkpoint"`
}

// WriteMarker writes .flashcli_model.json under cacheDir.
func WriteMarker(cacheDir, preset, checkpoint string) error {
	if err := os.MkdirAll(cacheDir, 0o755); err != nil {
		return err
	}
	blob, err := json.MarshalIndent(markerData{Preset: preset, Checkpoint: checkpoint}, "", "  ")
	if err != nil {
		return err
	}
	blob = append(blob, '\n')
	return os.WriteFile(filepath.Join(cacheDir, ".flashcli_model.json"), blob, 0o644)
}

// ReadMarker returns the checkpoint recorded in cacheDir's marker, if any.
func ReadMarker(cacheDir string) (string, bool) {
	blob, err := os.ReadFile(filepath.Join(cacheDir, ".flashcli_model.json"))
	if err != nil {
		return "", false
	}
	var m markerData
	if err := json.Unmarshal(blob, &m); err != nil || m.Checkpoint == "" {
		return "", false
	}
	return m.Checkpoint, true
}
