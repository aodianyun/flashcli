#!/usr/bin/env bash
# Build and (optionally) publish flashcli-go release artifacts.
#
# Usage:
#   bash scripts/release_go.sh                 # build artifacts + sha256sums
#   bash scripts/release_go.sh --upload        # build then publish via `gh`
#   FLASHCLI_GO_TARGETS="linux/amd64" bash scripts/release_go.sh
#
# Artifacts (dist/go/):
#   flashcli-<os>-<arch>   (raw binaries; consumed by install.sh)
#   sha256sums.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${FLASHCLI_GO_DIST:-$ROOT/dist/go}"
UPLOAD=0
for arg in "$@"; do
  case "$arg" in
    --upload) UPLOAD=1 ;;
    -h|--help) echo "usage: release_go.sh [--upload]"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

bash "$ROOT/scripts/build_go.sh" "$OUT"

VERSION="$(python3 - "$ROOT/pyproject.toml" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(m.group(1) if m else "")
PY
)"
echo "release version: ${VERSION}"

if [ "$UPLOAD" = "1" ]; then
  command -v gh >/dev/null 2>&1 || { echo "error: gh CLI not found" >&2; exit 1; }
  tag="v${VERSION}"
  echo "creating GitHub release ${tag} ..."
  gh release create "$tag" \
    "$OUT"/flashcli-* "$OUT"/sha256sums.txt \
    --title "flashcli ${VERSION}" \
    --notes "flashcli-go ${VERSION} (static binaries + sha256sums)" \
    || gh release upload "$tag" "$OUT"/flashcli-* "$OUT"/sha256sums.txt --clobber
  echo "[ok] uploaded ${tag}"
else
  echo "[ok] artifacts in $OUT"
  echo "    publish:  gh release create v${VERSION} $OUT/flashcli-* $OUT/sha256sums.txt"
  echo "    gitee:    upload the same files to the Gitee releases page"
fi
