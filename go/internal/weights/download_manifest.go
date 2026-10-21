package weights

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
)

// downloadManifestName records the expected remote file set for a weights
// destination. It is the host's download-completeness contract and is
// independent of any bundle-declared readiness rules.
const downloadManifestName = ".flashcli_download.json"

type downloadManifest struct {
	Repo     string             `json:"repo"`
	Revision string             `json:"revision"`
	Files    []manifestFileMeta `json:"files"`
}

type manifestFileMeta struct {
	Path string `json:"path"`
	Size int64  `json:"size"`
}

func downloadManifestPath(dest string) string {
	return filepath.Join(dest, downloadManifestName)
}

// isDownloadMetadata reports host bookkeeping files that must never satisfy a
// bundle's allow_patterns / require_any_patterns readiness check.
func isDownloadMetadata(name string) bool {
	return name == downloadManifestName ||
		name == incompleteMarker ||
		strings.HasPrefix(name, downloadManifestName+".tmp-")
}

// readDownloadManifest loads the manifest for dest if it belongs to repo.
// Revision is intentionally not part of the match: bundles pin immutable
// revisions, and ModelScope may resolve a fallback revision name.
func readDownloadManifest(dest, repo string) (*downloadManifest, bool) {
	blob, err := os.ReadFile(downloadManifestPath(dest))
	if err != nil {
		return nil, false
	}
	var m downloadManifest
	if json.Unmarshal(blob, &m) != nil || len(m.Files) == 0 {
		return nil, false
	}
	if strings.TrimSpace(m.Repo) != strings.TrimSpace(repo) {
		return nil, false
	}
	return &m, true
}

func writeDownloadManifest(dest, repo, rev string, files []remoteFile) error {
	m := downloadManifest{Repo: repo, Revision: rev}
	for _, f := range files {
		m.Files = append(m.Files, manifestFileMeta{Path: f.Path, Size: f.Size})
	}
	blob, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dest, downloadManifestName+".tmp-")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err := tmp.Write(append(blob, '\n')); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, 0o644); err != nil {
		return err
	}
	return os.Rename(tmpName, downloadManifestPath(dest))
}

func manifestFiles(m *downloadManifest) []remoteFile {
	out := make([]remoteFile, 0, len(m.Files))
	for _, f := range m.Files {
		out = append(out, remoteFile{Path: f.Path, Size: f.Size})
	}
	return out
}

// manifestMissing returns expected files that are absent, empty, or whose size
// does not match the recorded remote size (size>0). This is the host-level
// completeness check: a partial download is never "complete".
func manifestMissing(dest string, files []remoteFile) []remoteFile {
	var missing []remoteFile
	for _, f := range files {
		target := filepath.Join(dest, filepath.FromSlash(f.Path))
		info, err := os.Stat(target)
		if err != nil || info.IsDir() || (f.Size > 0 && info.Size() != f.Size) {
			missing = append(missing, f)
		}
	}
	return missing
}
