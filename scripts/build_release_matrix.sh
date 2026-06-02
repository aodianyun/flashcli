#!/usr/bin/env bash
# Generic release matrix builder — reads bundles/<name>/release-matrix.env
#
#   bash scripts/build_release_matrix.sh --bundle pi05_libero
#   bash scripts/build_release_matrix.sh --bundle qwen_nvfp4 --cuda-tag 124 --skip-pack
#   cd bundles/pi05_libero && bash ../../scripts/build_release_matrix.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/load_release_matrix.sh
source "${SCRIPT_DIR}/lib/load_release_matrix.sh"
# shellcheck source=lib/bundle_hooks.sh
source "${SCRIPT_DIR}/lib/bundle_hooks.sh"
# shellcheck source=lib/matrix_python.sh
source "${SCRIPT_DIR}/lib/matrix_python.sh"
# shellcheck source=lib/matrix_cuda.sh
source "${SCRIPT_DIR}/lib/matrix_cuda.sh"
# shellcheck source=lib/probe_native_abi.sh
source "${SCRIPT_DIR}/lib/probe_native_abi.sh"
# shellcheck source=lib/verify_native_abi.sh
source "${SCRIPT_DIR}/lib/verify_native_abi.sh"

BUNDLE_ARG=""
REPO_ROOT="${FLASHRT_REPO:-}"
GIT_REF="${GIT_REF:-main}"
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
DRY_RUN=0
CHECK_ONLY=0
PACK_ONLY=0
SKIP_PACK=0
INSTALL_PYTHON=0
INSTALL_PYTHON_METHOD="${FLASHCLI_INSTALL_PYTHON_METHOD:-auto}"
SKIP_CUDA_VERIFY=0
ONLY_CUDA=""
ONLY_PY=""

log() { printf '[matrix] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

trap 'kill 0; exit 130' INT
trap 'kill 0; exit 143' TERM

usage() {
  cat <<EOF
Build a bundle native matrix from release-matrix.env (cuda × python cells → lib/).

Usage:
  bash scripts/build_release_matrix.sh --bundle NAME [OPTIONS]

Options:
  --bundle NAME             Bundle id (e.g. pi05_libero, qwen_nvfp4)
  --repo-root DIR           FlashRT source (default: FLASHRT_REPO or auto-detect)
  --cuda-tag TAG            Build one CUDA line only (124 or 130)
  --python-minor NNN        Build one Python ABI only (310, 311, 312)
  --git-ref REF             Passed to manifest finalize (default: main)
  -j, --jobs N              Parallel cmake jobs per cell
  --pack-only               Finalize manifest + pack existing lib/
  --skip-pack               Build/merge lib/ only; skip finalize + zip
  --install-python          Run install_python_for_matrix.sh
  --install-python-method M auto|apt|deadsnakes|standalone
  --check-only              Verify python + nvcc layout
  --skip-cuda-verify        Do not require nvcc version match
  --dry-run
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) BUNDLE_ARG="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --cuda-tag) ONLY_CUDA="$2"; shift 2 ;;
    --python-minor) ONLY_PY="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    -j|--jobs) JOBS="$2"; shift 2 ;;
    --pack-only) PACK_ONLY=1; shift ;;
    --skip-pack) SKIP_PACK=1; shift ;;
    --install-python) INSTALL_PYTHON=1; shift ;;
    --install-python-method) INSTALL_PYTHON_METHOD="$2"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --skip-cuda-verify) SKIP_CUDA_VERIFY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ "$(uname -s)" != Linux ]]; then
  die "Release matrix build requires Linux (got $(uname -s))"
fi

BUNDLE_DIR="$(resolve_bundle_dir "${FLASHCLI_ROOT}" "${BUNDLE_ARG}")" \
  || die "Cannot resolve bundle directory"
load_release_matrix_config "${BUNDLE_DIR}" || die "Invalid release-matrix.env"

HOOK_RUNNER="${SCRIPT_DIR}/lib/bundle_hook_runner.sh"
PACK_SCRIPT="${SCRIPT_DIR}/pack_bundle.sh"
FINALIZE_CUDA_TAG="${RELEASE_FINALIZE_CUDA_TAG:-130}"

[[ -f "${HOOK_RUNNER}" ]] || die "Missing ${HOOK_RUNNER}"
[[ -f "${PACK_SCRIPT}" ]] || die "Missing ${PACK_SCRIPT}"

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
  if [[ "${PACK_ONLY}" -eq 0 && "${CHECK_ONLY}" -eq 0 ]]; then
    die "Set FLASHRT_REPO or pass --repo-root"
  fi
}

resolve_repo_root

check_matrix_layout() {
  ensure_python_matrix "${FLASHCLI_ROOT}" "${PY_MINORS}" "${ONLY_PY}" 0
  local cuda py py_bin skip_verify=0
  [[ "${SKIP_CUDA_VERIFY}" -eq 1 ]] && skip_verify=1
  for cuda in ${CUDA_TAGS}; do
    [[ -z "${ONLY_CUDA}" || "${ONLY_CUDA}" == "${cuda}" ]] || continue
    activate_cuda_toolkit "${cuda}" "${skip_verify}"
    for py in ${PY_MINORS}; do
      [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
      py_bin="$(python_bin_for_minor "${py}")"
      log "OK sm${MATRIX_SM}-cu${cuda}-linux-x86_64-py${py} → ${py_bin} @ ${CUDA_HOME}"
    done
  done
}

run_build_cell() {
  local cuda="$1" py="$2"
  local py_bin build_dir skip_verify=0
  py_bin="$(python_bin_for_minor "${py}")"
  build_dir="${FLASHCLI_ROOT}/.build-matrix/${RELEASE_BUNDLE_NAME}-cu${cuda}-py${py}"

  log "======== ${RELEASE_BUNDLE_NAME} sm${MATRIX_SM}-cu${cuda}-linux-x86_64-py${py} ========"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: bundle_hook_runner cell --python-bin ${py_bin} --cuda-tag ${cuda} --build-dir ${build_dir}"
    return 0
  fi

  [[ "${SKIP_CUDA_VERIFY}" -eq 1 ]] && skip_verify=1
  activate_cuda_toolkit "${cuda}" "${skip_verify}"

  bash "${HOOK_RUNNER}" cell "${BUNDLE_DIR}" \
    --repo-root "${REPO_ROOT}" \
    --python-bin "${py_bin}" \
    --python-minor "${py}" \
    --sm "${MATRIX_SM}" \
    --cuda-tag "${cuda}" \
    --git-ref "${GIT_REF}" \
    --build-dir "${build_dir}" \
    -j "${JOBS}"
}

pack_multi_zip() {
  log "Finalizing manifest + release zip (${RELEASE_BUNDLE_NAME})"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: finalize + pack_bundle.sh"
    return 0
  fi
  bash "${HOOK_RUNNER}" finalize "${BUNDLE_DIR}" \
    --repo-root "${REPO_ROOT}" \
    --sm "${MATRIX_SM}" \
    --cuda-tag "${FINALIZE_CUDA_TAG}" \
    --git-ref "${GIT_REF}"
  bash "${PACK_SCRIPT}" \
    --bundle-dir "${BUNDLE_DIR}" \
    --repo-root "${REPO_ROOT}"
}

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  check_matrix_layout
  log "check-only passed (${RELEASE_BUNDLE_NAME})"
  exit 0
fi

if [[ "${PACK_ONLY}" -eq 1 ]]; then
  pack_multi_zip
  log "Done (pack-only). Artifact: ${BUNDLE_DIR}/dist/${ZIP_PREFIX}-*-sm${MATRIX_SM}-multi-linux-x86_64-*.zip"
  exit 0
fi

if [[ "${INSTALL_PYTHON}" -eq 1 && "${DRY_RUN}" -eq 0 ]]; then
  install_python_matrix "${FLASHCLI_ROOT}" "${PY_MINORS}" "${ONLY_PY}" "${INSTALL_PYTHON_METHOD}"
fi

ensure_python_matrix "${FLASHCLI_ROOT}" "${PY_MINORS}" "${ONLY_PY}" "${INSTALL_PYTHON}" "${INSTALL_PYTHON_METHOD}"

for cuda in ${CUDA_TAGS}; do
  [[ -z "${ONLY_CUDA}" || "${ONLY_CUDA}" == "${cuda}" ]] || continue
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    run_build_cell "${cuda}" "${py}"
  done
done

verify_built_native_python_abi() {
  local verify_cuda="${CUDA_TAGS}" verify_py="${PY_MINORS}"
  [[ -n "${ONLY_CUDA}" ]] && verify_cuda="${ONLY_CUDA}"
  [[ -n "${ONLY_PY}" ]] && verify_py="${ONLY_PY}"
  log "Verifying Python ABI for lib/*.so (matrix interpreters, cu${verify_cuda}, py${verify_py})"
  verify_native_lib_python_abi \
    "${BUNDLE_DIR}" "${MATRIX_SM}" "${verify_cuda}" "linux" "x86_64" "${verify_py}" 1
  log "Python ABI verify OK"
}

if [[ "${DRY_RUN}" -eq 0 && "${PACK_ONLY}" -eq 0 && "${CHECK_ONLY}" -eq 0 ]]; then
  verify_built_native_python_abi
  if [[ -n "${SM120_CUDA_TAGS:-}" ]]; then
    log "Verifying sm120 Python ABI (Blackwell cu${SM120_CUDA_TAGS})"
    verify_native_lib_python_abi \
      "${BUNDLE_DIR}" "120" "${SM120_CUDA_TAGS}" "linux" "x86_64" "${PY_MINORS}" 1
  fi
fi

if [[ "${DRY_RUN}" -eq 0 && "${SKIP_PACK}" -eq 0 ]]; then
  pack_multi_zip
fi

if [[ "${SKIP_PACK}" -eq 1 ]]; then
  log "Done (skip-pack). lib/ → ${BUNDLE_DIR}/lib"
else
  log "Done. Artifact: ${BUNDLE_DIR}/dist/${ZIP_PREFIX}-*-sm${MATRIX_SM}-multi-linux-x86_64-*.zip"
fi
