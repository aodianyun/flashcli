#!/usr/bin/env bash
# Build one CUDA line inside Docker — invoked by scripts/release_bundle.sh
#
#   bash scripts/lib/docker_matrix_build.sh 124
#
set -euo pipefail

CUDA_TAG="${1:-}"
if [[ "${CUDA_TAG}" != "124" && "${CUDA_TAG}" != "130" ]]; then
  echo "[docker-matrix] ERROR: cuda tag must be 124 or 130 (got ${CUDA_TAG:-empty})" >&2
  exit 1
fi

FLASHCLI_ROOT="${FLASHCLI_ROOT:-/workspace/flashcli}"
FLASHRT_REPO="${FLASHRT_REPO:-/workspace/FlashRT}"
GIT_REF="${GIT_REF:-main}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
RELEASE_BUNDLE_NAME="${RELEASE_BUNDLE_NAME:-}"

log() { printf '[docker-matrix] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

[[ -n "${RELEASE_BUNDLE_NAME}" ]] || die "RELEASE_BUNDLE_NAME not set"
[[ -d "${FLASHCLI_ROOT}/scripts" ]] || die "Missing flashcli at ${FLASHCLI_ROOT}"
[[ -f "${FLASHRT_REPO}/CMakeLists.txt" && -d "${FLASHRT_REPO}/flash_rt" ]] \
  || die "Missing FlashRT at ${FLASHRT_REPO}"

export FLASHRT_REPO
export DEBIAN_FRONTEND=noninteractive

if ! command -v zip >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1; then
  log "Installing zip + rsync"
  apt-get update -qq
  apt-get install -y --no-install-recommends zip rsync ca-certificates curl
  rm -rf /var/lib/apt/lists/*
fi

command -v cmake >/dev/null 2>&1 || die "cmake not found in container"
command -v nvcc >/dev/null 2>&1 || die "nvcc not found in container"

_nvcc_ver="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
log "Container nvcc ${_nvcc_ver} (bundle=${RELEASE_BUNDLE_NAME}, cu${CUDA_TAG})"

case "${CUDA_TAG}" in
  124)
    export CUDA_HOME_CU124="${CUDA_HOME:-/usr/local/cuda}"
    export CUDA_HOME="${CUDA_HOME_CU124}"
    ;;
  130)
    export CUDA_HOME_CU130="${CUDA_HOME:-/usr/local/cuda}"
    export CUDA_HOME="${CUDA_HOME_CU130}"
    ;;
esac
export PATH="${CUDA_HOME}/bin:${PATH}"

log "Installing Python 3.10/3.11/3.12 for matrix"
bash "${FLASHCLI_ROOT}/scripts/install_python_for_matrix.sh" \
  --method auto --minors 310,311,312 || die "install_python_for_matrix.sh failed"

_env_file="${FLASHCLI_PYTHON_ENV:-/root/.flashcli/python-matrix.env}"
if [[ -f "${_env_file}" ]]; then
  # shellcheck source=/dev/null
  source "${_env_file}"
  log "Loaded ${_env_file}"
fi

bash "${FLASHCLI_ROOT}/scripts/build_release_matrix.sh" \
  --bundle "${RELEASE_BUNDLE_NAME}" \
  --repo-root "${FLASHRT_REPO}" \
  --cuda-tag "${CUDA_TAG}" \
  --git-ref "${GIT_REF}" \
  --skip-pack \
  --install-python \
  -j "${JOBS}"

log "cu${CUDA_TAG} line complete → ${FLASHCLI_ROOT}/bundles/${RELEASE_BUNDLE_NAME}/lib/"
