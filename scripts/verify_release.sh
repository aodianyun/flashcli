#!/usr/bin/env bash
# verify_release.sh — install a flashcli release into an isolated prefix and run
# smoke checks. Touches no host state (own FLASHCLI_HOME + install dir) and is
# safe to run in a throwaway container/VM.
#
# Usage:
#   bash scripts/verify_release.sh                     # latest release
#   bash scripts/verify_release.sh --version 1.0.0.2026.10.13
#   bash scripts/verify_release.sh --ref flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
#   bash scripts/verify_release.sh --source-dir .      # build this checkout instead
#   bash scripts/verify_release.sh --mirror            # Gitee + CN mirrors
#
# Env: FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF, PIP_INDEX_URL, HF_ENDPOINT
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=""
REF="flashcli-bundle/pi05_libero:1.0.4"
SOURCE_DIR=""
INSTALL_ARGS=()

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --github|--gitee|--mirror|--no-mirror) INSTALL_ARGS+=("$1"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Fully isolated from any real install.
export FLASHCLI_HOME="$work/home"
export FLASHCLI_GO_INSTALL_DIR="$work/bin"
export FLASHCLI_CLONE_DIR="$work/src"   # only used by --source-dir clone fallback
mkdir -p "$FLASHCLI_GO_INSTALL_DIR"

args=()
[ -n "$VERSION" ] && args+=(--version "$VERSION")
[ -n "$SOURCE_DIR" ] && args+=(--source-dir "$SOURCE_DIR")
if [ "${#INSTALL_ARGS[@]}" -gt 0 ]; then args+=("${INSTALL_ARGS[@]}"); fi

echo "[verify] prefix=$FLASHCLI_GO_INSTALL_DIR  FLASHCLI_HOME=$FLASHCLI_HOME"
echo "[verify] installing (${SOURCE_DIR:+source=$SOURCE_DIR}${SOURCE_DIR:-release}) ..."
bash "$ROOT/install.sh" "${args[@]}"

bin="$FLASHCLI_GO_INSTALL_DIR/flashcli"
[ -x "$bin" ] || { echo "FAIL: $bin not installed" >&2; exit 1; }

got="$("$bin" version | tr -d '[:space:]')"
echo "[verify] version: $got"
if [ -n "$VERSION" ] && [ "$got" != "$VERSION" ]; then
  echo "FAIL: version $got != requested $VERSION" >&2; exit 1
fi

echo "[verify] run --help (manifest-only, no full sync)"
"$bin" run "$REF" --help >/dev/null

echo "[verify] doctor"
"$bin" doctor || true

echo "[verify] OK ($got)"
