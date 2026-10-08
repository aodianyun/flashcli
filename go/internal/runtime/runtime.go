// Package runtime tracks per-bundle runtime identity and the bundle venv.
//
// Mirrors src/flashcli/bundle/runtime_id.py + marker.py + runtime/bundle_venv.py
// enough for the Go host to re-exec into “flashcli_bundle.infer“.
package runtime

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

var safeRe = regexp.MustCompile(`[^A-Za-z0-9._+\-]+`)

// IDFromRepo returns "<name>-<sha12>" for a FlashHub repo URL.
func IDFromRepo(repoURL, bundleName string) string {
	return safeName(bundleName) + "-" + digest(repoURL)
}

// IDFromPath returns "<name>-local-<sha12>" for a local bundle directory.
func IDFromPath(path, bundleName string) string {
	return safeName(bundleName) + "-local-" + digest(path)
}

func safeName(name string) string {
	safe := strings.Trim(safeRe.ReplaceAllString(strings.TrimSpace(name), "-"), "-")
	if safe == "" {
		return "bundle"
	}
	return safe
}

func digest(s string) string {
	sum := sha256.Sum256([]byte(strings.TrimSpace(s)))
	return hex.EncodeToString(sum[:])[:12]
}

// Dir returns the runtime directory under FLASHCLI_RUNTIMES_DIR.
func Dir(runtimeID string) string {
	return filepath.Join(paths.Runtimes(), runtimeID)
}

// VenvDir/VenvPython/FingerprintPath locate the bundle venv.
func VenvDir(runtimeID string) string  { return filepath.Join(Dir(runtimeID), "venv") }
func FingerprintPath(id string) string { return filepath.Join(Dir(id), ".venv-fingerprint") }

// VenvPython returns the venv interpreter path (python3 preferred).
func VenvPython(runtimeID string) (string, error) {
	root := VenvDir(runtimeID)
	for _, name := range []string{"python3", "python"} {
		candidate := filepath.Join(root, "bin", name)
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate, nil
		}
	}
	return "", os.ErrNotExist
}

// MarkerPath is the .runtime.json location.
func MarkerPath(runtimeID string) string { return filepath.Join(Dir(runtimeID), ".runtime.json") }

// ReadMarker returns the runtime marker map, or nil.
func ReadMarker(runtimeID string) map[string]any {
	blob, err := os.ReadFile(MarkerPath(runtimeID))
	if err != nil {
		return nil
	}
	var data map[string]any
	if err := json.Unmarshal(blob, &data); err != nil {
		return nil
	}
	return data
}

// WriteMarker writes the runtime marker.
func WriteMarker(runtimeID string, data map[string]any) error {
	if err := os.MkdirAll(Dir(runtimeID), 0o755); err != nil {
		return err
	}
	blob, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(MarkerPath(runtimeID), append(blob, '\n'), 0o644)
}

// InBundleVenv reports whether the current process is the re-exec'd infer.
func InBundleVenv(runtimeID string) bool {
	if os.Getenv("FLASHCLI_IN_BUNDLE_VENV") != "1" {
		return false
	}
	if runtimeID != "" && os.Getenv("FLASHCLI_RUNTIME_ID") != runtimeID {
		return false
	}
	return true
}

// PresetMarkerName is the bundle preset marker filename.
const PresetMarkerName = ".flashcli_bundle.json"

// PresetMarkerPath is Bundles()/<cacheKey>/.flashcli_bundle.json.
func PresetMarkerPath(cacheKey string) string {
	return filepath.Join(paths.Bundles(), filepath.FromSlash(cacheKey), PresetMarkerName)
}

// WritePresetMarker writes the bundle preset marker.
func WritePresetMarker(cacheKey string, data map[string]any) error {
	path := PresetMarkerPath(cacheKey)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	payload := map[string]any{}
	for k, v := range data {
		payload[k] = v
	}
	payload["cache_key"] = cacheKey
	blob, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(blob, '\n'), 0o644)
}

// ReadPresetMarker reads a bundle preset marker, or nil.
func ReadPresetMarker(cacheKey string) map[string]any {
	blob, err := os.ReadFile(PresetMarkerPath(cacheKey))
	if err != nil {
		return nil
	}
	var data map[string]any
	if json.Unmarshal(blob, &data) != nil {
		return nil
	}
	return data
}
