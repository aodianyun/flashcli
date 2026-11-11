#!/usr/bin/env bash
# Build and (optionally) publish flashcli-go release artifacts.
#
# Usage:
#   bash scripts/release_go.sh
#   bash scripts/release_go.sh --upload
#   bash scripts/release_go.sh --upload --notes-file dist/release-notes.md \
#     --windows-installer dist/windows/FlashServer-Setup-<version>.exe
#   FLASHCLI_GO_TARGETS="linux/amd64" bash scripts/release_go.sh
#
# Publishing (--upload):
#   1. Require a clean worktree and HEAD == origin/<target> (default main).
#   2. Ensure tag v<version> exists at HEAD and is pushed (creates it if needed).
#   3. GitHub release: `gh` if available, else GitHub API with GITHUB_TOKEN/GH_TOKEN.
#   4. Gitee release: Gitee OpenAPI with GITEE_TOKEN; the tag is created on Gitee
#      if missing (mirror syncs git but not release attachments).
# Repo overrides: GITEE_REPO (default aodiansoft/flashcli), GH_REPO (default aodianyun/flashcli).
#
# Options:
#   --upload                     Publish to GitHub + Gitee after building.
#   --notes-file FILE            Release notes body (Markdown) for both hosts.
#   --windows-installer FILE     Include FlashServer-Setup-<version>.exe as an asset.
#   --allow-non-target           Allow publishing from a branch other than the target.
#
# Environment:
#   FLASHCLI_RELEASE_TARGET      Target branch (default main).
#   FLASHCLI_WINDOWS_INSTALLER   Same as --windows-installer.
#   FLASHCLI_ALLOW_NON_TARGET=1  Same as --allow-non-target.
#   PYTHON_BIN                   Python for JSON helpers (default python3/python).
#
# Artifacts (dist/go/):
#   flashcli-<os>-<arch>          (raw binary; consumed by install.sh)
#   flashserver-<os>-<arch>       (resident scheduler)
#   flashserver-setup-<os>-<arch> (installer; Windows asset is .exe)
#   sha256sums.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${FLASHCLI_GO_DIST:-$ROOT/dist/go}"
GH_REPO="${GH_REPO:-aodianyun/flashcli}"
GITEE_REPO="${GITEE_REPO:-aodiansoft/flashcli}"
TARGET="${FLASHCLI_RELEASE_TARGET:-main}"
UPLOAD=0
ALLOW_NON_TARGET="${FLASHCLI_ALLOW_NON_TARGET:-0}"
NOTES_FILE=""
WINDOWS_INSTALLER="${FLASHCLI_WINDOWS_INSTALLER:-}"

die() { echo "error: $*" >&2; exit 1; }

usage() {
  sed -n '2,35p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --upload) UPLOAD=1; shift ;;
    --notes-file) NOTES_FILE="${2:-}"; shift 2 ;;
    --windows-installer) WINDOWS_INSTALLER="${2:-}"; shift 2 ;;
    --allow-non-target) ALLOW_NON_TARGET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

PY_BIN="${PYTHON_BIN:-}"
if [ -z "$PY_BIN" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY_BIN="$candidate"; break; fi
  done
fi

VERSION="$(sed -n 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$ROOT/pyproject.toml" | head -1)"
[ -n "$VERSION" ] || die "cannot read version from pyproject.toml"
TAG="v${VERSION}"

if [ "$UPLOAD" = "1" ]; then
  echo "release version: ${VERSION}"
  echo "release target:  ${TARGET}"
  [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ] \
    || die "working tree is not clean; commit or stash changes before publishing"
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  if [ "$branch" != "$TARGET" ] && [ "$ALLOW_NON_TARGET" != "1" ]; then
    die "current branch is '$branch', expected '$TARGET' (use FLASHCLI_ALLOW_NON_TARGET=1 only for tests)"
  fi
  if git -C "$ROOT" fetch -q origin "$TARGET" 2>/dev/null; then
    if [ "$ALLOW_NON_TARGET" != "1" ] && \
       [ "$(git -C "$ROOT" rev-parse HEAD)" != "$(git -C "$ROOT" rev-parse "origin/${TARGET}")" ]; then
      die "HEAD is not equal to origin/${TARGET}; push the release commit first"
    fi
  elif [ "$ALLOW_NON_TARGET" != "1" ]; then
    die "cannot fetch origin/${TARGET}; refusing to release an unverified branch"
  fi
fi

bash "$ROOT/scripts/build_go.sh" "$OUT"

ASSETS=()
for f in "$OUT"/flashcli-* "$OUT"/flashserver-* "$OUT"/sha256sums.txt; do
  [ -f "$f" ] && ASSETS+=("$f")
done
if [ -z "$WINDOWS_INSTALLER" ] && [ -n "${FLASHCLI_WINDOWS_INSTALLER:-}" ]; then
  WINDOWS_INSTALLER="$FLASHCLI_WINDOWS_INSTALLER"
fi
if [ -n "$WINDOWS_INSTALLER" ]; then
  [ -f "$WINDOWS_INSTALLER" ] || die "Windows installer not found: $WINDOWS_INSTALLER"
  expected_installer="FlashServer-Setup-${VERSION}.exe"
  [ "$(basename "$WINDOWS_INSTALLER")" = "$expected_installer" ] \
    || die "Windows installer must be named $expected_installer"
  ASSETS+=("$WINDOWS_INSTALLER")
  if command -v sha256sum >/dev/null 2>&1; then
    echo "Windows installer sha256: $(sha256sum "$WINDOWS_INSTALLER" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    echo "Windows installer sha256: $(shasum -a 256 "$WINDOWS_INSTALLER" | awk '{print $1}')"
  fi
fi
[ "${#ASSETS[@]}" -gt 0 ] || die "no release assets found in $OUT"

NOTES_BODY="flashcli-go ${VERSION} (static binaries + sha256sums)"
if [ -n "$NOTES_FILE" ]; then
  [ -f "$NOTES_FILE" ] || die "notes file not found: $NOTES_FILE"
  NOTES_BODY="$(cat "$NOTES_FILE")"
fi

_json_id() {
  "$PY_BIN" -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true
}

_json_release_body() {
  "$PY_BIN" - "$TAG" "$VERSION" "$TARGET" "$NOTES_BODY" <<'PY'
import json, sys
tag, version, target, body = sys.argv[1:5]
print(json.dumps({
    "tag_name": tag,
    "target_commitish": target,
    "name": f"flashcli {version}",
    "body": body,
}))
PY
}

ensure_tag() {
  local head remote_head
  head="$(git -C "$ROOT" rev-parse HEAD)"
  if git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    local local_head
    local_head="$(git -C "$ROOT" rev-parse "refs/tags/$TAG^{}")"
    [ "$local_head" = "$head" ] || die "tag $TAG points to $local_head, not HEAD $head"
  else
    git -C "$ROOT" tag "$TAG" "$head"
    echo "[i] created local tag $TAG"
  fi

  if git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG" 2>/dev/null | grep -q "refs/tags/$TAG$"; then
    remote_head="$(git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG^{}" 2>/dev/null | awk '{print $1}')"
    if [ -z "$remote_head" ]; then
      remote_head="$(git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG" 2>/dev/null | awk '{print $1}')"
    fi
    [ "$remote_head" = "$head" ] || die "remote tag $TAG points to $remote_head, not HEAD $head"
    echo "[i] tag $TAG already on origin"
    return 0
  fi

  git -C "$ROOT" push origin "$TAG" \
    || die "failed to push tag $TAG; publish requires the tag on origin"
  echo "[ok] pushed tag $TAG to origin"
}

publish_github() {
  local notes_args=()
  if [ -n "$NOTES_FILE" ]; then
    notes_args=(--notes-file "$NOTES_FILE")
  else
    notes_args=(--notes "$NOTES_BODY")
  fi
  if command -v gh >/dev/null 2>&1; then
    echo "GitHub: gh release ${TAG} ..."
    if gh release view "$TAG" >/dev/null 2>&1; then
      gh release upload "$TAG" "${ASSETS[@]}" --clobber \
        || { echo "error: gh release upload failed for $TAG" >&2; return 1; }
      gh release edit "$TAG" --title "flashcli ${VERSION}" "${notes_args[@]}" \
        || { echo "error: gh release edit failed for $TAG" >&2; return 1; }
    else
      gh release create "$TAG" "${ASSETS[@]}" \
        --title "flashcli ${VERSION}" "${notes_args[@]}" \
        || { echo "error: gh release create failed for $TAG" >&2; return 1; }
    fi
    echo "[ok] GitHub ${TAG}"
    return 0
  fi
  local tok="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [ -z "$tok" ]; then
    echo "[i] gh not found and GITHUB_TOKEN/GH_TOKEN unset — skipping GitHub upload"
    return 0
  fi
  local api="https://api.github.com/repos/${GH_REPO}"
  local rid
  rid="$(curl -sS -H "Authorization: token ${tok}" "${api}/releases/tags/${TAG}" | _json_id)"
  if [ -z "$rid" ]; then
    local payload
    payload="$(_json_release_body)"
    local resp code body
    resp="$(curl -sS -w $'\n%{http_code}' -X POST -H "Authorization: token ${tok}" \
      -H "Accept: application/vnd.github+json" "${api}/releases" \
      --data-binary "$payload")"
    code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
    rid="$(printf '%s' "$body" | _json_id)"
    if [ -z "$rid" ]; then
      echo "error: GitHub create release failed (HTTP ${code}): ${body}" >&2
      return 1
    fi
  fi
  local f
  for f in "${ASSETS[@]}"; do
    if ! curl -sS -X POST -H "Authorization: token ${tok}" -H "Content-Type: application/octet-stream" \
      --data-binary "@${f}" "https://uploads.github.com/repos/${GH_REPO}/releases/${rid}/assets?name=$(basename "$f")" >/dev/null; then
      echo "error: GitHub upload failed: $(basename "$f")" >&2
      return 1
    fi
    echo "  [ok] github <= $(basename "$f")"
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
      echo "error: GITEE_TOKEN looks like a GitHub token; use a Gitee personal access token" >&2
      return 1 ;;
  esac
  local api="https://gitee.com/api/v5/repos/${GITEE_REPO}"
  local sha
  sha="$(git -C "$ROOT" rev-parse "refs/tags/$TAG")"

  echo "Gitee: ensuring tag ${TAG} ..."
  local resp code body
  resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/tags" \
    -d "access_token=${GITEE_TOKEN}" -d "tag_name=${TAG}" -d "refs=${sha}" -d "message=flashcli ${VERSION}")"
  code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
  if [ "$code" = "201" ] || [ "$code" = "200" ]; then
    echo "[ok] Gitee tag ${TAG} created"
  elif printf '%s' "$body" | grep -qiE '已存在|already exists|exist'; then
    echo "[i] Gitee tag ${TAG} already exists"
  else
    echo "error: Gitee create tag failed (HTTP ${code}): ${body}" >&2
    return 1
  fi

  local rid
  rid="$(curl -sS "${api}/releases/tags/${TAG}?access_token=${GITEE_TOKEN}" | _json_id)"
  if [ -z "$rid" ]; then
    echo "Gitee: creating release ${TAG} ..."
    local body_args=(-d "access_token=${GITEE_TOKEN}" -d "tag_name=${TAG}" -d "name=flashcli ${VERSION}" -d "target_commitish=${TARGET}")
    if [ -n "$NOTES_FILE" ]; then
      body_args+=(--data-urlencode "body@${NOTES_FILE}")
    else
      body_args+=(--data-urlencode "body=${NOTES_BODY}")
    fi
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/releases" "${body_args[@]}")"
    code="$(printf '%s' "$resp" | tail -n1)"; body="$(printf '%s' "$resp" | sed '$d')"
    rid="$(printf '%s' "$body" | _json_id)"
    if [ -z "$rid" ]; then
      echo "error: Gitee create release failed (HTTP ${code}): ${body}" >&2
      return 1
    fi
  fi

  local f
  for f in "${ASSETS[@]}"; do
    resp="$(curl -sS -w $'\n%{http_code}' -X POST "${api}/releases/${rid}/attach_files" \
      -F "access_token=${GITEE_TOKEN}" -F "file=@${f}")"
    code="$(printf '%s' "$resp" | tail -n1)"
    if [ "$code" = "201" ] || [ "$code" = "200" ]; then
      echo "  [ok] gitee <= $(basename "$f")"
    else
      echo "error: Gitee upload failed for $(basename "$f") (HTTP ${code}): $(printf '%s' "$resp" | sed '$d')" >&2
      return 1
    fi
  done
  echo "[ok] Gitee ${TAG} (${GITEE_REPO})"
}

if [ "$UPLOAD" = "1" ]; then
  [ -n "$PY_BIN" ] || die "python3/python is required for release API helpers"
  ensure_tag
  failed=0
  publish_github || failed=1
  publish_gitee || failed=1
  [ "$failed" = "0" ] || die "one or more release uploads failed"
else
  echo "[ok] artifacts in $OUT"
  echo "    publish: GITHUB_TOKEN=... GITEE_TOKEN=... bash scripts/release_go.sh --upload"
  echo "    (or: gh auth login; GITEE_TOKEN=<gitee-token> bash scripts/release_go.sh --upload)"
fi
