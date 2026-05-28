#!/usr/bin/env bash
# Pack pi05_libero for CDN release — runtime files only (no README/build.sh/requirements-runtime.txt).
#
# Usage:
#   bash pack.sh
#   bash pack.sh --output /tmp/pi05_libero-sm89-cu124-linux-x86_64.zip
#   bash pack.sh --sm 89 --cuda-tag 124
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
# shellcheck source=../../scripts/lib/make_zip.sh
source "${FLASHCLI_ROOT}/scripts/lib/make_zip.sh"
OUTPUT=""
SM=""
CUDA_TAG=""
PYTHON_MINOR=""
OS_NAME="linux"
ARCH="x86_64"
GIT_REF="main"

usage() {
  cat <<EOF
Create a release zip with only files required to run inference.

Usage:
  bash pack.sh [OPTIONS]

Options:
  --output PATH     Output .zip path (default: ./dist/flashcli-bundle-pi05-<ref>-sm<SM>-cu<CUDA>-<os>-<arch>.zip)
  --sm SM           SM label in archive name (default: 89)
  --cuda-tag TAG    CUDA tag without 'cu' prefix, e.g. 124 (default: auto from nvcc, else 124)
  --python-minor NNN  Python ABI tag in name, e.g. 310 (default: from python3 on PATH)
  --git-ref REF     Git ref segment in archive name (default: main)
  -h, --help
EOF
}

log() { printf '[pi05-pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

detect_cuda_tag() {
  if command -v nvcc >/dev/null 2>&1; then
    local ver
    ver="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
    case "${ver}" in
      12.4|12.5|12.6) CUDA_TAG="124" ;;
      12.8|12.9) CUDA_TAG="128" ;;
      13.*) CUDA_TAG="130" ;;
      *)
        CUDA_TAG="${ver//./}"
        CUDA_TAG="${CUDA_TAG:0:3}"
        ;;
    esac
    log "cuda_tag=${CUDA_TAG} (nvcc ${ver})"
    return
  fi
  CUDA_TAG="124"
  log "cuda_tag=${CUDA_TAG} (nvcc not found; default)"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --sm) SM="$2"; shift 2 ;;
    --cuda-tag) CUDA_TAG="$2"; shift 2 ;;
    --python-minor) PYTHON_MINOR="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

SM="${SM:-89}"
if [[ -z "${CUDA_TAG}" ]]; then
  detect_cuda_tag
fi
if [[ -z "${PYTHON_MINOR}" ]]; then
  PYTHON_MINOR="$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"
fi

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"
[[ -f "${BUNDLE_DIR}/run.py" ]] || die "Missing run.py"
[[ -f "${BUNDLE_DIR}/_pi05_compat.py" ]] || die "Missing _pi05_compat.py"
NATIVE_LIB="${BUNDLE_DIR}/lib"
MULTI_ZIP=0
if [[ -d "${NATIVE_LIB}" ]] && compgen -G "${NATIVE_LIB}"/*.so >/dev/null; then
  MULTI_ZIP=1
  shopt -s nullglob
  KERNELS_SO=( "${NATIVE_LIB}"/flash_rt_kernels*.so )
  FA2_SO=( "${NATIVE_LIB}"/flash_rt_fa2*.so )
  shopt -u nullglob
else
  shopt -s nullglob
  KERNELS_SO=( "${BUNDLE_DIR}"/flash_rt_kernels*.so )
  FA2_SO=( "${BUNDLE_DIR}"/flash_rt_fa2*.so )
  shopt -u nullglob
fi
[[ ${#KERNELS_SO[@]} -ge 1 ]] || die "Missing flash_rt_kernels*.so (run build_pi05_bundle.sh first)"
[[ ${#FA2_SO[@]} -ge 1 ]] || die "Missing flash_rt_fa2*.so (run build_pi05_bundle.sh first)"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/ (run build.sh first)"

if [[ "${MULTI_ZIP}" -eq 1 ]]; then
  ARCHIVE_NAME="flashcli-bundle-pi05-${GIT_REF}-sm${SM}-multi-${OS_NAME}-${ARCH}"
else
  ARCHIVE_NAME="flashcli-bundle-pi05-${GIT_REF}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${ARCH}-py${PYTHON_MINOR}"
fi
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

STAGE_ROOT="${STAGE}/${ARCHIVE_NAME}"
mkdir -p "${STAGE_ROOT}"

cp -a "${BUNDLE_DIR}/flashcli-bundle.json" "${STAGE_ROOT}/"
cp -a "${BUNDLE_DIR}/run.py" "${BUNDLE_DIR}/_pi05_compat.py" "${STAGE_ROOT}/"
if [[ "${MULTI_ZIP}" -eq 1 ]]; then
  mkdir -p "${STAGE_ROOT}/lib"
  cp -a "${NATIVE_LIB}/." "${STAGE_ROOT}/lib/"
else
  for so in "${KERNELS_SO[@]}" "${FA2_SO[@]}"; do
    cp -a "${so}" "${STAGE_ROOT}/"
  done
fi
cp -a "${BUNDLE_DIR}/flash_rt" "${STAGE_ROOT}/"

if [[ -z "${OUTPUT}" ]]; then
  mkdir -p "${BUNDLE_DIR}/dist"
  OUTPUT="${BUNDLE_DIR}/dist/${ARCHIVE_NAME}.zip"
else
  OUTPUT="$(cd "$(dirname "${OUTPUT}")" && pwd)/$(basename "${OUTPUT}")"
  mkdir -p "$(dirname "${OUTPUT}")"
fi

rm -f "${OUTPUT}"
make_zip_archive "${STAGE}" "${ARCHIVE_NAME}" "${OUTPUT}" || die "Failed to create zip (install zip or use python3)"

log "Created ${OUTPUT}"
log "Contents:"
list_zip_archive "${OUTPUT}" | sed 's/^/  /' >&2 || true
