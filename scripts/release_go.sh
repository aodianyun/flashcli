#!/usr/bin/env bash
# Build and (optionally) publish flashcli-go release artifacts.
#
# Usage:
#   bash scripts/release_go.sh                 # build artifacts + sha256sums
#   bash scripts/release_go.sh --upload        # build, ensure tag, publish GitHub + Gitee
#   FLASHCLI_GO_TARGETS="linux/amd64" bash scripts/release_go.sh
#
# Publishing (--upload):
#   1. Ensure tag v<version> exists locally and is pushed to origin (GitHub).
#   2. GitHub release: `gh` if available, else GitHub API with GITHUB_TOKEN/GH_TOKEN.
#   3. Gitee release: Gitee OpenAPI with GITEE_TOKEN (personal access token);
#      the tag is created on Gitee if missing (mirror syncs git but not release
#      attachments, and tags may lag).
# Repo overrides: GITEE_REPO (default aodiansoft/flashcli), GH_REPO (default aodianyun/flashcli).
#
# Artifacts (dist/go/):
#   flashcli-<os>-<arch>   (raw binaries; consumed by install.sh)
#   sha256sums.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${FLASHCLI_GO_DIST:-$ROOT/dist/go}"
GH_REPO="${GH_REPO:-aodianyun/flashcli}"
GITEE_REPO="${GITEE_REPO:-aodiansoft/flashcli}"
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

_json_id() { python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true; }

ensure_tag() {
  if git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG" 2>/dev/null | grep -q "refs/tags/$TAG$"; then
    echo "[i] tag $TAG already on origin"
    git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
      || git -C "$ROOT" fetch -q origin "refs/tags/$TAG:refs/tags/$TAG" 2>/dev/null || true
    return 0
  fi
  if ! git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    git -C "$ROOT" tag "$TAG"
    echo "[i] created local tag $TAG"
  fi
  if git -C "$ROOT" push origin "$TAG" >/dev/null 2>&1; then
    echo "[ok] pushed tag $TAG to origin"
  else
    echo "[i] tag push skipped (no push access)"
  fi
}

publish_github() {
  if command -v gh >/dev/null 2>&1; then
    echo "GitHub: gh release ${TAG} ..."
    gh release create "$TAG" "$OUT"/flashcli-* "$OUT"/sha256sums.txt \
      --title "flashcli ${VERSION}" \
      --notes "flashcli-go ${VERSION} (static binaries + sha256sums)" \
      || gh release upload "$TAG" "$OUT"/flashcli-* "$OUT"/sha256sums.txt --clobber
    echo "[ok] GitHub ${TAG}"
    return 0
  fi
  tok="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [ -z "$tok" ]; then
    echo "[i] gh not found and GITHUB_TOKEN/GH_TOKEN unset — skipping GitHub upload"
    return 0
  fi
  api="https://api.github.com/repos/${GH_REPO}"
  rid="$(curl -sS -H "Authorization: token ${tok}" "${api}/releases/tags/${TAG}" | _json_id)"
  if [ -z "$rid" ]; then
    resp="$(curl -sS -w $'\n%{http_code}' -X POST -H "Authorization: token ${tok}" \
      -H "Accept: application/vnd.github+json" "${api}/releases" \
      -d "{\"tag_name\":\"${TAG}\",\"target_commitish\":\"dev\",\"name\":\"flashcli ${VERSION}\",\"body\":\"flashcli-go ${VERSION} (static binaries + sha256sums)\"}")"
    code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
    rid="$(printf '%s' "$body" | _json_id)"
    if [ -z "$rid" ]; then
      echo "[!] GitHub create release failed (HTTP ${code}): ${body}" >&2
      return 1
    fi
  fi
  for f in "$OUT"/flashcli-linux-amd64 "$OUT"/flashcli-linux-arm64 "$OUT"/sha256sums.txt; do
    [ -f "$f" ] || continue
    curl -sS -X POST -H "Authorization: token ${tok}" -H "Content-Type: application/octet-stream" \
      --data-binary "@${f}" "https://uploads.github.com/repos/${GH_REPO}/releases/${rid}/assets?name=$(basename "$f")" >/dev/null \
      && echo "  [ok] github <= $(basename "$f")" || echo "  [!] github upload failed: $(basename "$f")" >&2
  done
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
  api="https://gitee.com/api/v5/repos/${GITEE_REPO}"

  # Ensure the tag exists on Gitee. Gitee has no single-tag GET; create and
  # treat "already exists" as success.
  echo "Gitee: ensuring tag ${TAG} ..."
  sha="$(git -C "$ROOT" rev-parse "refs/tags/$TAG")"
  resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/tags" \
    -d "access_token=${GITEE_TOKEN}" -d "tag_name=${TAG}" -d "refs=${sha}" -d "message=flashcli ${VERSION}")"
  code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
  if [ "$code" = "201" ] || [ "$code" = "200" ]; then
    echo "[ok] Gitee tag ${TAG} created"
  elif printf '%s' "$body" | grep -qiE '已存在|already exists|exist'; then
    echo "[i] Gitee tag ${TAG} already exists"
  else
    echo "[!] Gitee create tag failed (HTTP ${code}): ${body}" >&2
    echo "    - ensure commit ${sha} exists on Gitee (repo sync), and GITEE_TOKEN is a Gitee token." >&2
    return 1
  fi

  rid="$(curl -sS "${api}/releases/tags/${TAG}?access_token=${GITEE_TOKEN}" | _json_id)"
  if [ -z "$rid" ]; then
    echo "Gitee: creating release ${TAG} ..."
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/releases" \
      -d "access_token=${GITEE_TOKEN}" -d "tag_name=${TAG}" \
      -d "name=flashcli ${VERSION}" -d "body=flashcli-go ${VERSION} (static binaries + sha256sums)" \
      -d "target_commitish=dev")"
    code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
    rid="$(printf '%s' "$body" | _json_id)"
    if [ -z "$rid" ]; then
      echo "[!] Gitee create release failed (HTTP ${code}): ${body}" >&2
      return 1
    fi
  fi

  for f in "$OUT"/flashcli-linux-amd64 "$OUT"/flashcli-linux-arm64 "$OUT"/sha256sums.txt; do
    [ -f "$f" ] || continue
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/releases/${rid}/attach_files" \
      -F "access_token=${GITEE_TOKEN}" -F "file=@${f}")"
    code="$(printf '%s' "$resp" | tail -n1)"
    if [ "$code" = "201" ] || [ "$code" = "200" ]; then
      echo "  [ok] gitee <= $(basename "$f")"
    else
      echo "  [!] gitee upload failed for $(basename "$f") (HTTP ${code}): $(printf '%s' "$resp" | sed '$d')" >&2
    fi
  done
  echo "[ok] Gitee ${TAG} (${GITEE_REPO})"
}

if [ "$UPLOAD" = "1" ]; then
  ensure_tag
  publish_github || true
  publish_gitee || true
else
  echo "[ok] artifacts in $OUT"
  echo "    publish: GITHUB_TOKEN=... GITEE_TOKEN=... bash scripts/release_go.sh --upload"
  echo "    (or: gh auth login; GITEE_TOKEN=<gitee-token> bash scripts/release_go.sh --upload)"
fi
