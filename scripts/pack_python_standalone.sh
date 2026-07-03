#!/usr/bin/env bash
# Download python-build-standalone install_only tarballs for FlashHub upload.
#
# Self-contained: curl + grep only (no flashcli / pip install).
#
# Output layout (upload dist/python-standalone/ to FlashHub):
#   python-standalone.json
#   standalone/{tag}/{triplet}/cpython-*.tar.gz
#
# Examples:
#   bash scripts/pack_python_standalone.sh
#   bash scripts/pack_python_standalone.sh --tag 20260602 --minors 310,311,312
#   bash scripts/pack_python_standalone.sh --triplets x86_64-unknown-linux-gnu,aarch64-unknown-linux-gnu --minors all
#   bash scripts/pack_python_standalone.sh --dry-run
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TAG="${FLASHCLI_PYTHON_STANDALONE_TAG:-20260602}"
OUTPUT_DIR="${FLASHCLI_ROOT}/dist/python-standalone"
TRIPLETS="x86_64-unknown-linux-gnu"
MINORS="all"
FORCE=0
DRY_RUN=0
QUIET=0
INCLUDE_PRE=0

GITHUB_REPO="astral-sh/python-build-standalone"
GIT_PROXY="${FLASHCLI_GIT_PROXY:-https://mirror.ghproxy.com/}"

log() { printf '[pack-python] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Download python-build-standalone tarballs into dist/python-standalone/ for FlashHub.

Usage:
  bash scripts/pack_python_standalone.sh [OPTIONS]

Options:
  --tag TAG             Release tag (default: ${TAG})
  --output-dir DIR      Output root (default: dist/python-standalone)
  --triplets LIST       Comma-separated triplets (default: x86_64-unknown-linux-gnu)
  --minors LIST         310,311,312 or all stable (default: all)
  --include-pre-release Include alpha/beta/rc builds
  --force               Re-download existing tarballs
  --dry-run             List matches only
  --quiet               No curl progress bar
  -h, --help
EOF
}

md5_file() {
  if command -v md5sum >/dev/null 2>&1; then
    md5sum "$1" | awk '{print $1}'
  elif command -v md5 >/dev/null 2>&1; then
    md5 -q "$1"
  else
    die "Need md5sum or md5 to write manifest"
  fi
}

curl_fetch() {
  local url="$1"
  curl -fsSL --connect-timeout 30 --max-time 600 -H 'User-Agent: flashcli-pack-python-standalone' "$url"
}

curl_download() {
  local url="$1"
  local dest="$2"
  local label="$3"
  mkdir -p "$(dirname "$dest")"
  local partial="${dest}.part"
  rm -f "$partial"

  local curl_args=(-fSL --connect-timeout 30 --max-time 3600 -H 'User-Agent: flashcli-pack-python-standalone' -o "$partial")
  if [[ "$QUIET" -eq 0 ]]; then
    curl_args+=(--progress-bar)
  else
    curl_args+=(-s)
  fi

  local candidate resolved=""
  for candidate in "$url" "${GIT_PROXY%/}/${url}"; do
    [[ -n "$candidate" ]] || continue
    log "Downloading ${label}"
    if curl "${curl_args[@]}" "$candidate"; then
      resolved="$candidate"
      break
    fi
    rm -f "$partial"
    log "Retry via mirror: ${label}"
  done
  [[ -n "$resolved" ]] || die "Download failed: ${label}"
  mv -f "$partial" "$dest"
  log "Done ${label} ($(wc -c < "$dest" | tr -d ' ') bytes)"
}

py_minor_from_name() {
  local name="$1"
  if [[ "$name" =~ cpython-3\.([0-9]+)\. ]]; then
    printf '3%s' "${BASH_REMATCH[1]}"
  fi
}

is_pre_release_name() {
  local name="$1"
  [[ "$name" =~ cpython-3\.[0-9]+\.[0-9]+[a-z] ]]
}

minor_wanted() {
  local py_minor="$1"
  [[ "$MINORS" == "all" ]] && return 0
  local m
  IFS=',' read -r -a _want <<< "$MINORS"
  for m in "${_want[@]}"; do
    m="${m// /}"
    [[ "$m" == "$py_minor" ]] && return 0
  done
  return 1
}

triplet_wanted() {
  local name="$1"
  local t
  IFS=',' read -r -a _triplets <<< "$TRIPLETS"
  for t in "${_triplets[@]}"; do
    t="${t// /}"
    [[ -n "$t" && "$name" == *"${t}"* ]] && return 0
  done
  return 1
}

list_install_only_names() {
  local tag="$1"
  local page="https://github.com/${GITHUB_REPO}/releases/expanded_assets/${tag}"
  local html=""
  html="$(curl_fetch "$page" 2>/dev/null)" || html="$(curl_fetch "${GIT_PROXY%/}/${page}" 2>/dev/null)" || die "Cannot fetch release page for ${tag}"
  grep -oE "cpython-3\.[0-9]+\.[0-9]+([a-z]+[0-9]+)?\\+${tag}-[^\"'[:space:]<>]+-install_only\\.tar\\.gz" <<< "$html" | sort -u
}

write_manifest() {
  local manifest="$1"
  shift
  python3 - "$manifest" "$TAG" "$@" <<'PY'
import json, sys
from pathlib import Path

manifest_path, tag = sys.argv[1], sys.argv[2]
files = []
for chunk in sys.argv[3:]:
    py_minor, triplet, path, url, size, md5 = chunk.split("|", 5)
    files.append({
        "py_minor": py_minor,
        "triplet": triplet,
        "tag": tag,
        "path": path,
        "filename": Path(path).name,
        "url": url,
        "size": int(size),
        "md5": md5,
    })
payload = {
    "format": "flashcli-python-standalone",
    "format_version": 1,
    "standalone_tag": tag,
    "upstream": f"https://github.com/astral-sh/python-build-standalone/releases/tag/{tag}",
    "files": files,
}
Path(manifest_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --triplets) TRIPLETS="$2"; shift 2 ;;
    --minors) MINORS="$2"; shift 2 ;;
    --include-pre-release) INCLUDE_PRE=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

log "Release tag: ${TAG}"
log "Triplets: ${TRIPLETS}"
log "Python minors: ${MINORS}"
log "Output: ${OUTPUT_DIR}"

mapfile -t ALL_NAMES < <(list_install_only_names "$TAG") 2>/dev/null || {
  ALL_NAMES=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && ALL_NAMES+=("$line")
  done < <(list_install_only_names "$TAG")
}
[[ ${#ALL_NAMES[@]} -gt 0 ]] || die "No install_only tarballs found for tag ${TAG}"

MATCHED=()
for name in "${ALL_NAMES[@]}"; do
  [[ "$name" == *"-install_only.tar.gz" ]] || continue
  [[ "$name" == *"_stripped"* ]] && continue
  if [[ "$INCLUDE_PRE" -eq 0 ]] && is_pre_release_name "$name"; then
    continue
  fi
  triplet_wanted "$name" || continue
  py_minor="$(py_minor_from_name "$name")"
  [[ -n "$py_minor" ]] || continue
  minor_wanted "$py_minor" || continue
  MATCHED+=("$name")
done

[[ ${#MATCHED[@]} -gt 0 ]] || die "No tarballs matched filters"

log "Matched ${#MATCHED[@]} tarball(s):"
for name in "${MATCHED[@]}"; do
  log "  py$(py_minor_from_name "$name")  ${name}"
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi

mkdir -p "$OUTPUT_DIR"
MANIFEST_ENTRIES=()
BASE_URL="https://github.com/${GITHUB_REPO}/releases/download/${TAG}"

for name in "${MATCHED[@]}"; do
  py_minor="$(py_minor_from_name "$name")"
  triplet=""
  if [[ "$name" =~ \+${TAG}-(.+)-install_only\.tar\.gz$ ]]; then
    triplet="${BASH_REMATCH[1]}"
  fi
  rel="standalone/${TAG}/${triplet}/${name}"
  dest="${OUTPUT_DIR}/${rel}"
  url="${BASE_URL}/${name}"

  if [[ -f "$dest" && "$FORCE" -eq 0 ]]; then
    size="$(wc -c < "$dest" | tr -d ' ')"
    hash="$(md5_file "$dest")"
    log "Skip ${rel} (${size} bytes, md5=${hash})"
  else
    curl_download "$url" "$dest" "$name"
    size="$(wc -c < "$dest" | tr -d ' ')"
    hash="$(md5_file "$dest")"
  fi
  MANIFEST_ENTRIES+=("${py_minor}|${triplet}|${rel}|${url}|${size}|${hash}")
done

write_manifest "${OUTPUT_DIR}/python-standalone.json" "${MANIFEST_ENTRIES[@]}"
log "Wrote ${OUTPUT_DIR}/python-standalone.json"
log "FlashHub upload dir: ${OUTPUT_DIR}"
_py_repo="${FLASHCLI_PYTHON_REPO:-}"
if [[ -z "${_py_repo}" ]]; then
  _api_base="${FLASHCLI_FLASHHUB_API:-https://flashhub-api.aodianyun.com/api/v1/repos}"
  _py_ver="${FLASHCLI_PYTHON_STANDALONE_VERSION:-1.0.0}"
  _py_repo="${_api_base%/}/flashcli-bundle/python-standalone:${_py_ver}"
fi
log "Suggested repo: ${_py_repo}"
