package weights

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

var checkpointWeightFiles = []string{"model.safetensors", "pytorch_model.bin", "model.bin"}

var normStatsCandidates = []string{
	"assets/physical-intelligence/libero/norm_stats.json",
	"assets/droid/norm_stats.json",
	"norm_stats.json",
	"meta/stats.json",
	"stats.json",
}

var sidecarTokens = []string{
	"normalizer", "unnormalizer", "processor", "preprocessor", "postprocessor",
}

// HasNormStatsSources mirrors Python has_norm_stats_sources.
func HasNormStatsSources(dir string) bool {
	if !isDir(dir) {
		return false
	}
	for _, rel := range normStatsCandidates {
		if fileExists(filepath.Join(dir, filepath.FromSlash(rel))) {
			return true
		}
	}
	pre, _ := filepath.Glob(filepath.Join(dir, "policy_*_normalizer_processor.safetensors"))
	post, _ := filepath.Glob(filepath.Join(dir, "policy_*_unnormalizer_processor.safetensors"))
	return len(pre) > 0 && len(post) > 0
}

// HasCheckpointWeightFiles mirrors Python has_checkpoint_weight_files.
func HasCheckpointWeightFiles(dir string) bool {
	if !isDir(dir) {
		return false
	}
	for _, name := range checkpointWeightFiles {
		if fileExists(filepath.Join(dir, name)) {
			return true
		}
	}
	if fileExists(filepath.Join(dir, "config.json")) && hasMainSafetensors(dir) {
		return true
	}
	if fileExists(filepath.Join(dir, "mtp.safetensors")) {
		return true
	}
	if matches, _ := filepath.Glob(filepath.Join(dir, "*.ckpt")); len(matches) > 0 {
		return true
	}
	return false
}

// HasUsableCheckpoint mirrors Python has_usable_checkpoint.
func HasUsableCheckpoint(dir string, requireNormStats bool) bool {
	if !HasCheckpointWeightFiles(dir) {
		return false
	}
	if requireNormStats && !HasNormStatsSources(dir) {
		return false
	}
	return true
}

// HasCachedWeightFiles mirrors Python has_cached_weight_files.
func HasCachedWeightFiles(dir string, allowPatterns []string, requireNormStats bool) bool {
	if !isDir(dir) {
		return false
	}
	if len(allowPatterns) > 0 {
		for _, pat := range allowPatterns {
			if !MatchFileUnder(dir, pat) {
				return false
			}
		}
		if requireNormStats && !HasNormStatsSources(dir) {
			return false
		}
		return true
	}
	return HasUsableCheckpoint(dir, requireNormStats)
}

// ExtraWeightsReady mirrors Python extra_weights_ready.
func ExtraWeightsReady(dir string, spec Spec) bool {
	if !isDir(dir) {
		return false
	}
	requireNS := spec.RequireNormStats
	if len(spec.RequireAnyPatterns) > 0 {
		ok := false
		for _, pat := range spec.RequireAnyPatterns {
			if MatchFileUnder(dir, pat) {
				ok = true
				break
			}
		}
		if ok && requireNS && !HasNormStatsSources(dir) {
			return false
		}
		return ok
	}
	if len(spec.AllowPatterns) > 0 {
		return HasCachedWeightFiles(dir, spec.AllowPatterns, requireNS)
	}
	return HasUsableCheckpoint(dir, requireNS)
}

// MatchFileUnder reports whether pattern matches any file under dir.
func MatchFileUnder(dir, pattern string) bool {
	found := false
	_ = filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		rel, relErr := filepath.Rel(dir, path)
		if relErr != nil {
			return nil
		}
		if matchPattern(filepath.ToSlash(rel), pattern) {
			found = true
			return fs.SkipAll
		}
		return nil
	})
	return found
}

func hasMainSafetensors(dir string) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".safetensors") {
			continue
		}
		lower := strings.ToLower(e.Name())
		sidecar := false
		for _, token := range sidecarTokens {
			if strings.Contains(lower, token) {
				sidecar = true
				break
			}
		}
		if !sidecar {
			return true
		}
	}
	return false
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
