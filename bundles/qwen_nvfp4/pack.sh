#!/usr/bin/env bash
# Pack qwen_nvfp4 for CDN release — runtime files only (no README/build.sh).
#
# Usage:
#   bash pack.sh
#   bash pack.sh --git-ref main
#   bash pack.sh --skip-matrix-verify   # partial lib/ (dev only)
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
# shellcheck source=../../scripts/lib/verify_native_matrix.sh
source "${FLASHCLI_ROOT}/scripts/lib/verify_native_matrix.sh"

OUTPUT=""
SM="120"
CUDA_TAG="130"
GIT_REF="main"
OS_NAME="linux"
ARCH="x86_64"
PY_MINORS="310 311 312"
SKIP_MATRIX_VERIFY=0

usage() {
  cat <<EOF
Create a release zip with only files required to run Qwen NVFP4 inference.

Expects lib/ from build_qwen_release_matrix.sh:
  sm120 × cu130 × linux-x86_64 × (py310, py311, py312)
  with flash_rt_kernels + flash_rt_fa2 per cell (NVFP4 is inside kernels on SM120).

Usage:
  bash pack.sh [OPTIONS]

Options:
  --output PATH           Output .zip (default: ./dist/flashcli-bundle-qwen_nvfp4-<ref>-sm120-multi-linux-x86_64.zip)
  --sm SM                 SM label (default: 120)
  --cuda-tag TAG          CUDA tag without cu prefix (default: 130)
  --python-minors LIST    Space-separated ABI tags, e.g. "310 311 312" (default)
  --git-ref REF           Git ref segment (default: main)
  --skip-matrix-verify    Do not require full cu130 × py310/311/312 matrix (dev only)
  -h, --help
EOF
}

log() { printf '[qwen-pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --sm) SM="$2"; shift 2 ;;
    --cuda-tag) CUDA_TAG="$2"; shift 2 ;;
    --python-minors) PY_MINORS="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    --skip-matrix-verify) SKIP_MATRIX_VERIFY=1; shift ;;
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
shopt -u nullglob

[[ ${#KERNELS_SO[@]} -ge 1 ]] || die "Missing lib/flash_rt_kernels*.so"
[[ ${#FA2_SO[@]} -ge 1 ]] || die "Missing lib/flash_rt_fa2*.so"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/"

if [[ "${SKIP_MATRIX_VERIFY}" -eq 0 ]]; then
  verify_native_matrix_lib "${NATIVE_LIB}" "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${ARCH}" \
    "${PY_MINORS}" flash_rt_kernels flash_rt_fa2 \
    || die "lib/ matrix incomplete (run build_qwen_release_matrix.sh or use --skip-matrix-verify)"
else
  log "Skipping full matrix verify (--skip-matrix-verify)"
fi

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
