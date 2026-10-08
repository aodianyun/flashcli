#!/usr/bin/env bash
# Build and (optionally) publish flashcli-go release artifacts.
#
# Usage:
#   bash scripts/release_go.sh                 # build artifacts + sha256sums
#   bash scripts/release_go.sh --upload        # publish to GitHub (gh) and Gitee (GITEE_TOKEN)
#   FLASHCLI_GO_TARGETS="linux/amd64" bash scripts/release_go.sh
#
# Publishing:
#   GitHub  — uses `gh` (must be authenticated).
#   Gitee   — uses the Gitee OpenAPI; set GITEE_TOKEN (personal access token).
#             Repo: GITEE_REPO (default aodiansoft/flashcli).
#   Gitee mirrors the git repo (branches/tags) from GitHub automatically, but
#   **release attachments are NOT mirrored** — they must be uploaded here.
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
TAG="v${VERSION}"
echo "release version: ${VERSION}"

publish_github() {
  if ! command -v gh >/dev/null 2>&1; then
    echo "[!] gh CLI not found — skipping GitHub upload" >&2
    return 1
  fi
  echo "creating GitHub release ${TAG} ..."
  gh release create "$TAG" \
    "$OUT"/flashcli-* "$OUT"/sha256sums.txt \
    --title "flashcli ${VERSION}" \
    --notes "flashcli-go ${VERSION} (static binaries + sha256sums)" \
    || gh release upload "$TAG" "$OUT"/flashcli-* "$OUT"/sha256sums.txt --clobber
  echo "[ok] GitHub ${TAG}"
}

publish_gitee() {
  if [ -z "${GITEE_TOKEN:-}" ]; then
    echo "[i] GITEE_TOKEN unset — skipping Gitee upload (release attachments are not auto-mirrored)"
    return 0
  fi
  case "${GITEE_TOKEN}" in
    ghp_*|github_pat_*)
      echo "[!] GITEE_TOKEN looks like a *GitHub* token. Use a Gitee personal access token" >&2
      echo "    (https://gitee.com/profile/personal_access_tokens)." >&2
      return 1 ;;
  esac
  repo="${GITEE_REPO:-aodiansoft/flashcli}"
  api="https://gitee.com/api/v5/repos/${repo}"

  _json_id() { python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true; }

  echo "Gitee: looking up release ${TAG} in ${repo} ..."
  rid="$(curl -sS "${api}/releases/tags/${TAG}?access_token=${GITEE_TOKEN}" | _json_id)"
  if [ -z "$rid" ]; then
    echo "Gitee: creating release ${TAG} ..."
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "$api/releases" \
      -d "access_token=${GITEE_TOKEN}" \
      -d "tag_name=${TAG}" \
      -d "name=flashcli ${VERSION}" \
      -d "body=flashcli-go ${VERSION} (static binaries + sha256sums)" \
      -d "target_commitish=dev")"
    code="$(printf '%s' "$resp" | tail -n1)"
    body="$(printf '%s' "$resp" | sed '$d')"
    rid="$(printf '%s' "$body" | _json_id)"
    if [ -z "$rid" ]; then
      echo "[!] Gitee create release failed (HTTP ${code}): ${body}" >&2
      echo "    - GITEE_TOKEN must be a Gitee personal access token (scope: projects)." >&2
      echo "    - the tag ${TAG} must exist on Gitee (repo sync, or: git push <gitee-remote> ${TAG})." >&2
      return 1
    fi
  fi

  for f in "$OUT"/flashcli-linux-amd64 "$OUT"/flashcli-linux-arm64 "$OUT"/sha256sums.txt; do
    [ -f "$f" ] || continue
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "$api/releases/${rid}/attach_files" \
      -F "access_token=${GITEE_TOKEN}" -F "file=@${f}")"
    code="$(printf '%s' "$resp" | tail -n1)"
    if [ "$code" = "201" ] || [ "$code" = "200" ]; then
      echo "  [ok] gitee <= $(basename "$f")"
    else
      echo "  [!] gitee upload failed for $(basename "$f") (HTTP ${code}): $(printf '%s' "$resp" | sed '$d')" >&2
    fi
  done
  echo "[ok] Gitee ${TAG}"
}

if [ "$UPLOAD" = "1" ]; then
  publish_github || true
  publish_gitee || true
else
  echo "[ok] artifacts in $OUT"
  echo "    publish GitHub: gh release create ${TAG} $OUT/flashcli-* $OUT/sha256sums.txt"
  echo "    publish Gitee : GITEE_TOKEN=<token> bash scripts/release_go.sh --upload"
fi
