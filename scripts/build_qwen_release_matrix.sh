#!/usr/bin/env bash
# Build qwen_nvfp4 release matrix:
#   sm120 × cu130 × linux-x86_64 × (py310, py311, py312) → one multi-env zip
#
# Usage:
#   export FLASHRT_REPO=/path/to/FlashRT
#   export CUDA_HOME_CU130=/usr/local/cuda-13.0
#   bash scripts/build_qwen_release_matrix.sh
#   bash scripts/build_qwen_release_matrix.sh --check-only
#   bash scripts/build_qwen_release_matrix.sh --python-minor 312
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE_DIR="${FLASHCLI_ROOT}/bundles/qwen_nvfp4"
BUILD_SH="${SCRIPT_DIR}/build_qwen_bundle.sh"
PACK_SH="${BUNDLE_DIR}/pack.sh"

CUDA_TAGS="130"
PY_MINORS="310 311 312"
SM="120"
GIT_REF="${GIT_REF:-main}"
REPO_ROOT="${FLASHRT_REPO:-}"
DRY_RUN=0
CHECK_ONLY=0
INSTALL_PYTHON=0
INSTALL_PYTHON_METHOD="${FLASHCLI_INSTALL_PYTHON_METHOD:-auto}"
SKIP_CUDA_VERIFY=0
ONLY_PY=""

log() { printf '[qwen-matrix] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<'EOF'
Build qwen_nvfp4 runtime zip: sm120 × cu130 × (py310, py311, py312).

Requires Linux + NVIDIA SM120 (Blackwell) build host, cmake, zip, nvcc 13.x.

  export FLASHRT_REPO=/path/to/FlashRT
  export CUDA_HOME_CU130=/usr/local/cuda-13.0
  bash scripts/build_qwen_release_matrix.sh

Options:
  --repo-root DIR       FlashRT source
  --python-minor NNN    Build one Python ABI only (310, 311, 312)
  --git-ref REF         Zip name segment (default: main)
  --install-python      Run scripts/install_python_for_matrix.sh
  --check-only          Verify python + nvcc; do not build
  --skip-cuda-verify    Do not require nvcc 13.x match (not for release)
  --dry-run
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --python-minor) ONLY_PY="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    --install-python) INSTALL_PYTHON=1; shift ;;
    --install-python-method) INSTALL_PYTHON_METHOD="$2"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --skip-cuda-verify) SKIP_CUDA_VERIFY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -f "${BUILD_SH}" ]] || die "Missing ${BUILD_SH}"
[[ -f "${PACK_SH}" ]] || die "Missing ${PACK_SH}"

python_candidates_for_minor() {
  local py="$1"
  local major="${py:0:1}" minor="${py:1:2}"
  local ver="python${major}.${minor}"
  local var="FLASHCLI_PY${py}_BIN"
  local override="${!var:-}"
  local root="${FLASHCLI_PYTHON_ROOT:-/opt/flashcli-python}"
  if [[ -n "${override}" ]]; then
    printf '%s\n' "${override}"
    return
  fi
  printf '%s\n' \
    "${ver}" \
    "/usr/local/bin/${ver}" \
    "/usr/bin/${ver}" \
    "${root}/${major}.${minor}/bin/${ver}" \
    "${root}/${major}.${minor}/bin/python3" \
    "/opt/python/${ver}/bin/${ver}"
}

python_bin_reports_minor() {
  local bin="$1" py="$2"
  local want_major="${py:0:1}" want_minor="${py:1:2}"
  [[ -x "${bin}" ]] || return 1
  local got_major got_minor
  got_major="$("${bin}" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)" || return 1
  got_minor="$("${bin}" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)" || return 1
  [[ "${got_major}" == "${want_major}" && "${got_minor}" == "${want_minor}" ]]
}

resolve_python_bin() {
  local py="$1"
  local candidate resolved=""
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    if command -v "${candidate}" >/dev/null 2>&1; then
      resolved="$(command -v "${candidate}")"
    elif [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    else
      continue
    fi
    if python_bin_reports_minor "${resolved}" "${py}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done < <(python_candidates_for_minor "${py}")
  return 1
}

python_bin_for_minor() {
  resolve_python_bin "$1" || die "No Python ${1:0:1}.${1:1:2} (py${1}). Set FLASHCLI_PY${1}_BIN=..."
}

cuda_home_for_tag() {
  local tag="$1"
  local var="CUDA_HOME_CU${tag}"
  local home="${!var:-}"
  if [[ -n "${home}" ]]; then
    printf '%s\n' "${home}"
    return
  fi
  for home in /usr/local/cuda-13.0 /usr/local/cuda-13 /usr/local/cuda; do
    [[ -x "${home}/bin/nvcc" ]] && { printf '%s\n' "${home}"; return; }
  done
  if [[ -n "${CUDA_HOME:-}" && -x "${CUDA_HOME}/bin/nvcc" ]]; then
    printf '%s\n' "${CUDA_HOME}"
  fi
}

activate_cuda_toolkit() {
  local tag="$1"
  local home
  home="$(cuda_home_for_tag "${tag}")"
  [[ -n "${home}" ]] || die "No CUDA toolkit for cu${tag}. Set CUDA_HOME_CU${tag}"
  export CUDA_HOME="${home}"
  export PATH="${CUDA_HOME}/bin:${PATH}"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found under ${CUDA_HOME}"
  local ver
  ver="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
  log "cu${tag}: CUDA_HOME=${CUDA_HOME} nvcc=${ver}"
  if [[ "${SKIP_CUDA_VERIFY}" -eq 0 && ! "${ver}" =~ ^13\. ]]; then
    die "nvcc ${ver} does not match cu130 (expected 13.x). Set CUDA_HOME_CU130 or use --skip-cuda-verify"
  fi
}

ensure_python_available() {
  local missing=()
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    resolve_python_bin "${py}" >/dev/null 2>&1 || missing+=("py${py}")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ "${INSTALL_PYTHON}" -eq 1 ]]; then
    local minors_csv
    minors_csv="$(IFS=,; echo "${missing[*]#py}")"
    bash "${SCRIPT_DIR}/install_python_for_matrix.sh" \
      --method "${INSTALL_PYTHON_METHOD}" --minors "${minors_csv}"
    missing=()
    for py in ${PY_MINORS}; do
      [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
      resolve_python_bin "${py}" >/dev/null 2>&1 || missing+=("py${py}")
    done
  fi
  [[ ${#missing[@]} -eq 0 ]] || die "Missing Python: ${missing[*]}"
}

check_matrix_layout() {
  ensure_python_available
  activate_cuda_toolkit "130"
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    log "OK sm${SM}-cu130-linux-x86_64-py${py} → $(python_bin_for_minor "${py}")"
  done
}

run_build() {
  local py="$1"
  local py_bin build_dir
  py_bin="$(python_bin_for_minor "${py}")"
  build_dir="${FLASHCLI_ROOT}/.build-matrix/qwen-cu130-py${py}"

  log "======== sm${SM}-cu130-linux-x86_64-py${py} ========"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: ${BUILD_SH} --python-bin ${py_bin} --python-minor ${py} --sm ${SM} --cuda-tag 130"
    return 0
  fi

  activate_cuda_toolkit "130"

  local -a build_args=(
    --bundle-dir "${BUNDLE_DIR}"
    --variant all
    --python-bin "${py_bin}"
    --python-minor "${py}"
    --sm "${SM}"
    --cuda-tag 130
    --git-ref "${GIT_REF}"
    --build-dir "${build_dir}"
    --merge-native
    --skip-manifest
  )
  [[ -n "${REPO_ROOT}" ]] && build_args+=(--repo-root "${REPO_ROOT}")

  bash "${BUILD_SH}" "${build_args[@]}"
}

pack_multi_zip() {
  log "Finalizing manifest + release zip"
  local -a fin_args=(--bundle-dir "${BUNDLE_DIR}" --finalize-matrix-manifest --sm "${SM}" --cuda-tag 130)
  [[ -n "${REPO_ROOT}" ]] && fin_args+=(--repo-root "${REPO_ROOT}")
  bash "${BUILD_SH}" "${fin_args[@]}"
  bash "${PACK_SH}" --sm "${SM}" --git-ref "${GIT_REF}"
}

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  check_matrix_layout
  log "check-only passed"
  exit 0
fi

ensure_python_available

for py in ${PY_MINORS}; do
  [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
  run_build "${py}"
done

if [[ "${DRY_RUN}" -eq 0 ]]; then
  pack_multi_zip
fi

log "Done. Artifact: ${BUNDLE_DIR}/dist/flashcli-bundle-qwen_nvfp4-${GIT_REF}-sm${SM}-multi-linux-x86_64.zip"
log "Upload to CDN, then update models.yaml bundle.zip for qwen3-8b-nvfp4 / qwen36-27b-nvfp4"
