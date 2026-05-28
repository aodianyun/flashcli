#!/usr/bin/env bash
# Pack qwen_nvfp4 for CDN release — runtime files only (no README/build.sh).
#
# Usage:
#   bash pack.sh
#   bash pack.sh --git-ref main
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT=""
SM="120"
GIT_REF="main"
OS_NAME="linux"
ARCH="x86_64"

usage() {
  cat <<EOF
Create a release zip with only files required to run Qwen NVFP4 inference.

Usage:
  bash pack.sh [OPTIONS]

Options:
  --output PATH     Output .zip (default: ./dist/flashcli-bundle-qwen_nvfp4-<ref>-sm120-multi-linux-x86_64.zip)
  --sm SM           SM label (default: 120)
  --git-ref REF     Git ref segment (default: main)
  -h, --help
EOF
}

log() { printf '[qwen-pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --sm) SM="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"
[[ -f "${BUNDLE_DIR}/run.py" ]] || die "Missing run.py"
[[ -f "${BUNDLE_DIR}/serve.py" ]] || die "Missing serve.py"
NATIVE_LIB="${BUNDLE_DIR}/lib"
[[ -d "${NATIVE_LIB}" ]] || die "Missing lib/ (run build_qwen_release_matrix.sh first)"

shopt -s nullglob
KERNELS_SO=( "${NATIVE_LIB}"/flash_rt_kernels*.so )
FA2_SO=( "${NATIVE_LIB}"/flash_rt_fa2*.so )
FP4_SO=( "${NATIVE_LIB}"/flash_rt_fp4*.so )
shopt -u nullglob

[[ ${#KERNELS_SO[@]} -ge 1 ]] || die "Missing lib/flash_rt_kernels*.so"
[[ ${#FA2_SO[@]} -ge 1 ]] || die "Missing lib/flash_rt_fa2*.so"
[[ ${#FP4_SO[@]} -ge 1 ]] || die "Missing lib/flash_rt_fp4*.so (NVFP4 required)"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/"

ARCHIVE_NAME="flashcli-bundle-qwen_nvfp4-${GIT_REF}-sm${SM}-multi-${OS_NAME}-${ARCH}"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

STAGE_ROOT="${STAGE}/${ARCHIVE_NAME}"
mkdir -p "${STAGE_ROOT}"

cp -a "${BUNDLE_DIR}/flashcli-bundle.json" "${STAGE_ROOT}/"
for f in run.py serve.py _qwen_util.py _flashrt_serve.py; do
  [[ -f "${BUNDLE_DIR}/${f}" ]] || die "Missing ${f}"
  cp -a "${BUNDLE_DIR}/${f}" "${STAGE_ROOT}/"
done
mkdir -p "${STAGE_ROOT}/lib"
cp -a "${NATIVE_LIB}/." "${STAGE_ROOT}/lib/"
cp -a "${BUNDLE_DIR}/flash_rt" "${STAGE_ROOT}/"

if [[ -z "${OUTPUT}" ]]; then
  mkdir -p "${BUNDLE_DIR}/dist"
  OUTPUT="${BUNDLE_DIR}/dist/${ARCHIVE_NAME}.zip"
else
  OUTPUT="$(cd "$(dirname "${OUTPUT}")" && pwd)/$(basename "${OUTPUT}")"
  mkdir -p "$(dirname "${OUTPUT}")"
fi

rm -f "${OUTPUT}"
(
  cd "${STAGE}"
  command -v zip >/dev/null 2>&1 || die "zip command not found"
  zip -rq "${OUTPUT}" "${ARCHIVE_NAME}"
)

log "Created ${OUTPUT}"
log "Contents:"
zipinfo -1 "${OUTPUT}" | sed 's/^/  /' >&2
