#!/usr/bin/env bash
# Unified bundle pack: matrix verify + ABI probe + zip (FlashRT ABI + build timestamp in name).
#
#   bash scripts/pack_bundle.sh --bundle-dir bundles/pi05_libero --repo-root ../FlashRT
#   cd bundles/qwen_nvfp4 && bash ../../scripts/pack_bundle.sh --repo-root ../../FlashRT
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/load_release_matrix.sh
source "${SCRIPT_DIR}/lib/load_release_matrix.sh"
# shellcheck source=lib/make_zip.sh
source "${SCRIPT_DIR}/lib/make_zip.sh"
# shellcheck source=lib/verify_native_matrix.sh
source "${SCRIPT_DIR}/lib/verify_native_matrix.sh"
# shellcheck source=lib/probe_native_abi.sh
source "${SCRIPT_DIR}/lib/probe_native_abi.sh"
# shellcheck source=lib/native_naming.sh
source "${SCRIPT_DIR}/lib/native_naming.sh"
# shellcheck source=lib/release_naming.sh
source "${SCRIPT_DIR}/lib/release_naming.sh"
# shellcheck source=lib/verify_native_abi.sh
source "${SCRIPT_DIR}/lib/verify_native_abi.sh"
# shellcheck source=lib/pack_verify.sh
source "${SCRIPT_DIR}/lib/pack_verify.sh"
# shellcheck source=lib/matrix_python.sh
source "${SCRIPT_DIR}/lib/matrix_python.sh"

BUNDLE_ARG=""
BUNDLE_DIR=""
REPO_ROOT="${FLASHRT_REPO:-}"
OUTPUT=""
SKIP_MATRIX_VERIFY=0
OS_NAME="linux"
ARCH="x86_64"

log() { printf '[pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Pack a bundle release zip (runtime files only).

Archive name:
  {ZIP_PREFIX}-{flashrt_abi}-sm{SM}-multi-{os}-{arch}-{YYYYMMDD-HHMMSS}.zip

Usage:
  bash scripts/pack_bundle.sh [OPTIONS]

Options:
  --bundle-dir DIR      Bundle directory (default: cwd if release-matrix.env present)
  --bundle NAME         Bundle id (e.g. pi05_libero)
  --repo-root DIR       FlashRT source (for version segment; default: auto-detect)
  --output PATH         Output .zip path (default: bundle/dist/<archive>.zip)
  --skip-matrix-verify  Skip lib/ matrix + ABI checks (dev only)
  -h, --help
EOF
}

is_flashrt_repo() {
  [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]
}

resolve_repo_root() {
  if [[ -n "${REPO_ROOT}" ]]; then
    REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
    is_flashrt_repo "${REPO_ROOT}" || die "Invalid FlashRT repo: ${REPO_ROOT}"
    return
  fi
  local candidate
  for candidate in \
    "$(cd "${FLASHCLI_ROOT}/.." && pwd)" \
    "$(cd "${FLASHCLI_ROOT}/../.." && pwd)"; do
    if is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      log "FlashRT repo: ${REPO_ROOT} (auto-detected)"
      return
    fi
  done
  die "Set FLASHRT_REPO or pass --repo-root"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --bundle) BUNDLE_ARG="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --skip-matrix-verify) SKIP_MATRIX_VERIFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ -n "${BUNDLE_DIR}" ]]; then
  BUNDLE_DIR="$(cd "${BUNDLE_DIR}" && pwd)"
else
  BUNDLE_DIR="$(resolve_bundle_dir "${FLASHCLI_ROOT}" "${BUNDLE_ARG}")" \
    || die "Cannot resolve bundle directory"
fi

load_release_matrix_config "${BUNDLE_DIR}" || die "Invalid release-matrix.env"
resolve_repo_root

PACK_FILES="${RELEASE_PACK_FILES:-}"
[[ -n "${PACK_FILES}" ]] || die "RELEASE_PACK_FILES not set in release-matrix.env"

native_lib="${BUNDLE_DIR}/lib"
[[ -d "${native_lib}" ]] || die "Missing lib/ (run release_bundle.sh or build_release_matrix.sh first)"

shopt -s nullglob
kernels_so=( "${native_lib}"/flash_rt_kernels*.so )
fa2_so=( "${native_lib}"/flash_rt_fa2*.so )
shopt -u nullglob
[[ ${#kernels_so[@]} -ge 1 ]] || die "Missing lib/flash_rt_kernels*.so"
[[ ${#fa2_so[@]} -ge 1 ]] || die "Missing lib/flash_rt_fa2*.so"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/"

if [[ "${SKIP_MATRIX_VERIFY}" -eq 0 ]]; then
  pack_verify_lib_matrix_and_abi \
    "${BUNDLE_DIR}" "${MATRIX_SM}" "${CUDA_TAGS}" "${OS_NAME}" "${ARCH}" "${PY_MINORS}"
else
  log "Skipping matrix verify (--skip-matrix-verify)"
fi

ARCHIVE_NAME="$(release_archive_basename "${ZIP_PREFIX}" "${REPO_ROOT}" "${MATRIX_SM}" "${OS_NAME}" "${ARCH}")"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

STAGE_ROOT="${STAGE}/${ARCHIVE_NAME}"
mkdir -p "${STAGE_ROOT}"

for entry in ${PACK_FILES}; do
  local_path="${BUNDLE_DIR}/${entry}"
  [[ -e "${local_path}" ]] || die "Missing pack file: ${entry}"
  if [[ -d "${local_path}" ]]; then
    mkdir -p "${STAGE_ROOT}/${entry}"
    cp -a "${local_path}/." "${STAGE_ROOT}/${entry}/"
  else
    cp -a "${local_path}" "${STAGE_ROOT}/"
  fi
done

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
