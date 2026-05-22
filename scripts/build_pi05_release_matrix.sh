#!/usr/bin/env bash
# Build the pi05_libero urgent release matrix:
#   sm89 × (cu124, cu130) × linux-x86_64 × (py310, py311, py312) → 6 zips
#
# This script LOOPS cuda × python and, for each cell:
#   1) selects CUDA toolkit via CUDA_HOME (see cuda_home_for_tag)
#   2) verifies nvcc matches the requested --cuda-tag
#   3) builds native .so with that Python (separate BUILD_DIR per cell)
#   4) packs dist/*.zip
#
# It does NOT install CUDA or Python unless you pass --install-python (apt, Debian/Ubuntu).
#
# Usage:
#   export FLASHRT_REPO=/path/to/FlashRT
#   export CUDA_HOME_CU124=/usr/local/cuda-12.4
#   export CUDA_HOME_CU130=/usr/local/cuda-13.0
#   bash scripts/build_pi05_release_matrix.sh
#   bash scripts/build_pi05_release_matrix.sh --cuda-tag 124 --python-minor 312
#   bash scripts/build_pi05_release_matrix.sh --check-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUNDLE_DIR="${FLASHCLI_ROOT}/bundles/pi05_libero"
BUILD_SH="${SCRIPT_DIR}/build_pi05_bundle.sh"
PACK_SH="${BUNDLE_DIR}/pack.sh"

CUDA_TAGS="124 130"
PY_MINORS="310 311 312"
SM="89"
GIT_REF="${GIT_REF:-main}"
REPO_ROOT="${FLASHRT_REPO:-}"
DRY_RUN=0
CHECK_ONLY=0
INSTALL_PYTHON=0
INSTALL_PYTHON_METHOD="${FLASHCLI_INSTALL_PYTHON_METHOD:-auto}"
SKIP_CUDA_VERIFY=0
ONLY_CUDA=""
ONLY_PY=""

log() { printf '[pi05-matrix] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
warn() { log "WARN: $*"; }

usage() {
  cat <<'EOF'
Build pi05_libero runtime zips: sm89 × (cu124, cu130) × (py310, py311, py312).

Prerequisites (NOT done automatically except --install-python):
  • Linux + NVIDIA GPU + cmake + zip + rsync
  • python3.10, python3.11, python3.12 on PATH (or FLASHCLI_PY310_BIN / …)
  • Two CUDA toolkits for true cu124+cu130 matrix, OR build one CUDA line at a time:
      export CUDA_HOME_CU124=/usr/local/cuda-12.4
      export CUDA_HOME_CU130=/usr/local/cuda-13.0
    Script puts matching bin/ on PATH before each cell.

Fast paths:
  • Only CUDA 12.4 host today:
      bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
  • One Python missing: install then rerun single cell:
      bash scripts/build_pi05_release_matrix.sh --install-python
      bash scripts/build_pi05_release_matrix.sh --cuda-tag 124 --python-minor 312

Options:
  --repo-root DIR       FlashRT source (default: FLASHRT_REPO or auto-detect)
  --cuda-tag TAG        Build one CUDA line only (124 or 130)
  --python-minor NNN    Build one Python ABI only (310, 311, 312)
  --git-ref REF         Zip name segment (default: main)
  --install-python      Run scripts/install_python_for_matrix.sh (apt + standalone fallback)
  --install-python-method auto|apt|deadsnakes|standalone
  --check-only          Verify python + nvcc layout; do not build
  --skip-cuda-verify    Do not require nvcc version to match --cuda-tag (not for release)
  --dry-run             Print planned commands
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --cuda-tag) ONLY_CUDA="$2"; shift 2 ;;
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

# Map py310 -> executable path. Order: FLASHCLI_PY310_BIN, then common install locations.
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
  resolve_python_bin "$1" || die "No Python ${1:0:1}.${1:1:2} found (py${1}). Set FLASHCLI_PY${1}_BIN=/path/to/python"
}

apt_pkg_available() {
  apt-cache show "$1" >/dev/null 2>&1
}

install_python_one_minor() {
  local py="$1"
  local major="${py:0:1}" minor="${py:1:2}"
  local ver="python${major}.${minor}"
  if resolve_python_bin "${py}" >/dev/null 2>&1; then
    log "py${py}: already available ($(resolve_python_bin "${py}"))"
    return 0
  fi
  local pkgs=("${ver}")
  if apt_pkg_available "${ver}-dev"; then
    pkgs+=("${ver}-dev")
  fi
  if ! apt_pkg_available "${ver}"; then
    warn "py${py}: apt has no package ${ver} on this OS — skip apt (use /usr/local or FLASHCLI_PY${py}_BIN)"
    return 1
  fi
  log "py${py}: apt install ${pkgs[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
}

INSTALL_PY_SH="${SCRIPT_DIR}/install_python_for_matrix.sh"

install_python_matrix() {
  [[ -f "${INSTALL_PY_SH}" ]] || die "Missing ${INSTALL_PY_SH}"
  local minors=()
  local py
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    minors+=("${py}")
  done
  local minors_csv
  minors_csv="$(IFS=,; echo "${minors[*]}")"
  log "Running install_python_for_matrix.sh --method ${INSTALL_PYTHON_METHOD} --minors ${minors_csv}"
  bash "${INSTALL_PY_SH}" --method "${INSTALL_PYTHON_METHOD}" --minors "${minors_csv}"
  local env_file="${FLASHCLI_PYTHON_ENV:-/root/.flashcli/python-matrix.env}"
  if [[ -f "${env_file}" ]]; then
    # shellcheck source=/dev/null
    source "${env_file}"
    log "Loaded ${env_file}"
  fi
}

ensure_python_available() {
  local missing=()
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    if ! resolve_python_bin "${py}" >/dev/null 2>&1; then
      missing+=("py${py}")
    fi
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ "${INSTALL_PYTHON}" -eq 1 ]]; then
    install_python_matrix
    missing=()
    for py in ${PY_MINORS}; do
      [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
      if ! resolve_python_bin "${py}" >/dev/null 2>&1; then
        missing+=("py${py}")
      fi
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
      return 0
    fi
  fi
  die "Missing Python: ${missing[*]}. Found on this host: $(ls /usr/local/bin/python3.* /usr/bin/python3.* 2>/dev/null | tr '\n' ' ' || echo '(none)'). Set FLASHCLI_PY312_BIN=... or install 3.12 separately; use --python-minor to build a subset."
}

# Resolve CUDA toolkit root for catalog tag (124 / 130).
cuda_home_for_tag() {
  local tag="$1"
  local var="CUDA_HOME_CU${tag}"
  local home="${!var:-}"
  if [[ -n "${home}" ]]; then
    printf '%s\n' "${home}"
    return
  fi
  case "${tag}" in
    124)
      for home in /usr/local/cuda-12.4 /usr/local/cuda-12.6 /usr/local/cuda-12; do
        [[ -x "${home}/bin/nvcc" ]] && { printf '%s\n' "${home}"; return; }
      done
      ;;
    130)
      for home in /usr/local/cuda-13.0 /usr/local/cuda-13 /usr/local/cuda; do
        [[ -x "${home}/bin/nvcc" ]] && { printf '%s\n' "${home}"; return; }
      done
      ;;
  esac
  if [[ -n "${CUDA_HOME:-}" && -x "${CUDA_HOME}/bin/nvcc" ]]; then
    printf '%s\n' "${CUDA_HOME}"
    return
  fi
  printf '\n'
}

nvcc_release_for_tag() {
  case "$1" in
    124) echo "12.4" ;;
    130) echo "13.0" ;;
    *) die "Unknown cuda tag: $1" ;;
  esac
}

nvcc_tag_from_version() {
  local ver="$1"
  case "${ver}" in
    12.4|12.5|12.6) echo "124" ;;
    12.8|12.9) echo "128" ;;
    13.*) echo "130" ;;
    *)
      local compact="${ver//./}"
      echo "${compact:0:3}"
      ;;
  esac
}

activate_cuda_toolkit() {
  local tag="$1"
  local home
  home="$(cuda_home_for_tag "${tag}")"
  if [[ -z "${home}" ]]; then
    die "No CUDA toolkit for cu${tag}. Set CUDA_HOME_CU${tag} (e.g. export CUDA_HOME_CU130=/usr/local/cuda-13.0)"
  fi
  export CUDA_HOME="${home}"
  export PATH="${CUDA_HOME}/bin:${PATH}"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found under ${CUDA_HOME}"
  local ver detected_tag
  ver="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
  detected_tag="$(nvcc_tag_from_version "${ver}")"
  log "cu${tag}: CUDA_HOME=${CUDA_HOME} nvcc=${ver} (detected tag ${detected_tag})"
  if [[ "${SKIP_CUDA_VERIFY}" -eq 0 && "${detected_tag}" != "${tag}" ]]; then
    die "nvcc ${ver} does not match requested cu${tag} (expected ~$(nvcc_release_for_tag "${tag}")). Fix CUDA_HOME_CU${tag} or use --cuda-tag ${detected_tag}"
  fi
}

check_matrix_layout() {
  ensure_python_available
  for cuda in ${CUDA_TAGS}; do
    [[ -z "${ONLY_CUDA}" || "${ONLY_CUDA}" == "${cuda}" ]] || continue
    activate_cuda_toolkit "${cuda}"
    for py in ${PY_MINORS}; do
      [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
      local py_bin
      py_bin="$(python_bin_for_minor "${py}")"
      log "OK sm${SM}-cu${cuda}-linux-x86_64-py${py} → ${py_bin} @ ${CUDA_HOME}"
    done
  done
}

run_build() {
  local cuda="$1" py="$2"
  local py_bin build_dir
  py_bin="$(python_bin_for_minor "${py}")"
  build_dir="${FLASHCLI_ROOT}/.build-matrix/cu${cuda}-py${py}"

  log "======== sm${SM}-cu${cuda}-linux-x86_64-py${py} ========"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: CUDA_HOME=\$CUDA_HOME_CU${cuda} nvcc → cu${cuda}"
    log "DRY: ${BUILD_SH} --python-bin ${py_bin} --python-minor ${py} --cuda-tag ${cuda} --build-dir ${build_dir}"
    log "DRY: ${PACK_SH} --cuda-tag ${cuda} --python-minor ${py}"
    return 0
  fi

  activate_cuda_toolkit "${cuda}"

  local -a build_args=(
    --bundle-dir "${BUNDLE_DIR}"
    --python-bin "${py_bin}"
    --python-minor "${py}"
    --sm "${SM}"
    --cuda-tag "${cuda}"
    --git-ref "${GIT_REF}"
    --build-dir "${build_dir}"
    --merge-native
    --skip-manifest
  )
  if [[ -n "${REPO_ROOT}" ]]; then
    build_args+=(--repo-root "${REPO_ROOT}")
  fi

  bash "${BUILD_SH}" "${build_args[@]}"
}

pack_multi_zip() {
  log "Finalizing manifest + single multi-env zip"
  local -a fin_args=(--bundle-dir "${BUNDLE_DIR}" --finalize-matrix-manifest)
  if [[ -n "${REPO_ROOT}" ]]; then
    fin_args+=(--repo-root "${REPO_ROOT}")
  fi
  bash "${BUILD_SH}" "${fin_args[@]}"
  bash "${PACK_SH}" --sm "${SM}" --git-ref "${GIT_REF}"
}

if [[ "${INSTALL_PYTHON}" -eq 1 && "${CHECK_ONLY}" -eq 0 && "${DRY_RUN}" -eq 0 ]]; then
  install_python_matrix
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  check_matrix_layout
  log "check-only passed"
  exit 0
fi

ensure_python_available

for cuda in ${CUDA_TAGS}; do
  [[ -z "${ONLY_CUDA}" || "${ONLY_CUDA}" == "${cuda}" ]] || continue
  for py in ${PY_MINORS}; do
    [[ -z "${ONLY_PY}" || "${ONLY_PY}" == "${py}" ]] || continue
    run_build "${cuda}" "${py}"
  done
done

if [[ "${DRY_RUN}" -eq 0 ]]; then
  pack_multi_zip
fi

log "Done. Artifact: ${BUNDLE_DIR}/dist/flashcli-bundle-pi05-${GIT_REF}-sm${SM}-multi-linux-x86_64.zip"
log "Upload to CDN, then: flashcli models envs pi05_libero"
