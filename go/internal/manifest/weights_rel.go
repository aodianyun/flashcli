package manifest

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

// VariantWeightsRel returns the checkpoint-relative weights directory for a
// variant:
//
//   - an explicit `weights_dir` if set; else
//   - a directory derived from the weights identity (source/repo/revision/url),
//     so two variants with identical weights map to the same dir (shared) and
//     different weights map to different dirs (never collide);
//   - `checkpoint/<variant>` for local/uncertain specs.
func VariantWeightsRel(block map[string]any, name string) string {
	if r := strings.TrimSpace(mapString(block["weights_dir"], "")); r != "" {
		return strings.Trim(r, "/")
	}
	spec, _ := block["weights"].(map[string]any)
	source := strings.ToLower(mapString(spec["source"], "huggingface"))
	repo := strings.TrimSpace(mapString(spec["repo"], ""))
	rev := strings.TrimSpace(mapString(spec["revision"], "main"))
	url := strings.TrimSpace(mapString(spec["url"], ""))
	relative := strings.TrimSpace(mapString(spec["relative_dir"], ""))
	if repo == "" && url == "" && relative == "" {
		return "checkpoint/" + name
	}
	sum := sha256.Sum256([]byte(source + "|" + repo + "|" + rev + "|" + url + "|" + relative))
	return "checkpoint/" + hex.EncodeToString(sum[:])[:12]
}
