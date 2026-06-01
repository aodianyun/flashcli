#!/usr/bin/env bash
# Unified one-command bundle release: Docker (cu124 + cu130) → lib/ matrix → zip.
#
# Each bundle provides release-matrix.env + pack.sh; this script orchestrates FlashRT
# clone, per-CUDA Docker builds, manifest finalize, matrix/ABI verify, and zip.
#
# Usage:
#   bash scripts/release_bundle.sh --bundle pi05_libero --clean
#   bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
#   cd bundles/qwen_nvfp4 && bash release.sh --clean
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${FLASHCLI_ROOT}/.." && pwd)"
DOCKER_BUILD="${SCRIPT_DIR}/lib/docker_matrix_build.sh"
# shellcheck source=lib/ensure_flashrt_repo.sh
source "${SCRIPT_DIR}/lib/ensure_flashrt_repo.sh"
# shellcheck source=lib/load_release_matrix.sh
source "${SCRIPT_DIR}/lib/load_release_matrix.sh"
# shellcheck source=lib/bundle_hooks.sh
source "${SCRIPT_DIR}/lib/bundle_hooks.sh"
# shellcheck source=lib/release_docker_state.sh
source "${SCRIPT_DIR}/lib/release_docker_state.sh"

_BUILTIN_FLASHRT_GIT_URL="https://github.com/LiangSu8899/FlashRT.git"
_BUILTIN_FLASHRT_REF="main"
_DEFAULT_FLASHRT_DEST="${WORKSPACE_ROOT}/FlashRT"
_ENV_FLASHRT_REPO="${FLASHRT_REPO:-}"
_ENV_FLASHRT_GIT_URL="${FLASHRT_GIT_URL:-}"
_ENV_FLASHRT_REF="${FLASHRT_REF:-}"

BUNDLE_ARG=""
REPO_ROOT=""
FLASHRT_GIT_URL="${_BUILTIN_FLASHRT_GIT_URL}"
FLASHRT_REF="${_BUILTIN_FLASHRT_REF}"
USER_REPO_ROOT=0
USER_FLASHRT_GIT_URL=0
USER_FLASHRT_REF=0

GIT_REF="${GIT_REF:-main}"
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
USE_DOCKER=1
CLEAN=0
DRY_RUN=0
SKIP_VALIDATE=0
ONLY_CUDA=""

log() { printf '[release] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

ACTIVE_DOCKER_CONTAINER=""
ACTIVE_DOCKER_LOGS_PID=""
NATIVE_PID=""

kill_process_tree() {
  local pid="$1" sig="${2:-TERM}"
  local children child

  [[ -z "${pid}" ]] && return 0
  children="$(pgrep -P "${pid}" 2>/dev/null || true)"
  for child in ${children}; do
    kill_process_tree "${child}" "${sig}"
  done
  kill "-${sig}" "${pid}" 2>/dev/null || true
}

cleanup_on_interrupt() {
  local exit_code="${1:-130}"

  if [[ -n "${ACTIVE_DOCKER_LOGS_PID}" ]]; then
    kill "${ACTIVE_DOCKER_LOGS_PID}" 2>/dev/null || true
    wait "${ACTIVE_DOCKER_LOGS_PID}" 2>/dev/null || true
    ACTIVE_DOCKER_LOGS_PID=""
  fi

  if [[ -n "${ACTIVE_DOCKER_CONTAINER}" ]]; then
    log "Stopping Docker container ${ACTIVE_DOCKER_CONTAINER}..."
    release_docker_stop_container "${ACTIVE_DOCKER_CONTAINER}"
    release_docker_state_unregister "${ACTIVE_DOCKER_CONTAINER}"
    ACTIVE_DOCKER_CONTAINER=""
  fi

  release_docker_stop_all "${FLASHCLI_ROOT}"

  if [[ -n "${NATIVE_PID}" ]] && kill -0 "${NATIVE_PID}" 2>/dev/null; then
    log "Stopping native build (pid ${NATIVE_PID})..."
    kill_process_tree "${NATIVE_PID}" TERM
    sleep 1
    kill_process_tree "${NATIVE_PID}" KILL
    NATIVE_PID=""
  fi

  exit "${exit_code}"
}

install_interrupt_traps() {
  trap 'cleanup_on_interrupt 130' INT
  trap 'cleanup_on_interrupt 143' TERM
}

usage() {
  cat <<EOF
Build and pack a flashcli model bundle release zip (multi-env lib/).

Bundles declare matrix in bundles/<name>/release-matrix.env:
  pi05_libero   sm89  × cu124/cu130 × py310/311/312
  qwen_nvfp4    sm120 × cu130 × py310/311/312

FlashRT (default — auto clone/update):
  url: ${_BUILTIN_FLASHRT_GIT_URL}
  ref: ${_BUILTIN_FLASHRT_REF}
  dir: ${_DEFAULT_FLASHRT_DEST}

Usage:
  bash scripts/release_bundle.sh --bundle NAME [OPTIONS]

Options:
  --bundle NAME           Bundle id (e.g. pi05_libero, qwen_nvfp4)
  --repo-root DIR         Use local FlashRT (skip clone)
  --flashrt-repo URL      Git remote when cloning
  --flashrt-ref REF       FlashRT branch/tag/commit (default: ${_BUILTIN_FLASHRT_REF})
  --git-ref REF           Passed to manifest finalize (default: main)
  --image-cu124 IMAGE     Docker image for cu124 line
  --image-cu130 IMAGE     Docker image for cu130 line
  --cuda-tag TAG          Build one CUDA line only (124 or 130)
  --native                Build on host (no Docker)
  --clean                 Remove bundle lib/, dist/, .build-matrix/, .native-cache/
  --skip-validate         Skip flashcli bundle validate
  -j, --jobs N            Parallel cmake jobs per cell
  --dry-run
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) BUNDLE_ARG="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; USER_REPO_ROOT=1; shift 2 ;;
    --flashrt-repo) FLASHRT_GIT_URL="$2"; USER_FLASHRT_GIT_URL=1; shift 2 ;;
    --flashrt-ref) FLASHRT_REF="$2"; USER_FLASHRT_REF=1; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    --image-cu124) IMAGE_CU124="$2"; shift 2 ;;
    --image-cu130) IMAGE_CU130="$2"; shift 2 ;;
    --cuda-tag) ONLY_CUDA="$2"; shift 2 ;;
    --native) USE_DOCKER=0; shift ;;
    --clean) CLEAN=1; shift ;;
    --skip-validate) SKIP_VALIDATE=1; shift ;;
    -j|--jobs) JOBS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ -n "${_ENV_FLASHRT_REPO}" && "${USER_REPO_ROOT}" -eq 0 ]]; then
  REPO_ROOT="${_ENV_FLASHRT_REPO}"
  USER_REPO_ROOT=1
fi
if [[ -n "${_ENV_FLASHRT_GIT_URL}" && "${USER_FLASHRT_GIT_URL}" -eq 0 ]]; then
  FLASHRT_GIT_URL="${_ENV_FLASHRT_GIT_URL}"
  USER_FLASHRT_GIT_URL=1
fi
if [[ -n "${_ENV_FLASHRT_REF}" && "${USER_FLASHRT_REF}" -eq 0 ]]; then
  FLASHRT_REF="${_ENV_FLASHRT_REF}"
  USER_FLASHRT_REF=1
fi

BUNDLE_DIR="$(resolve_bundle_dir "${FLASHCLI_ROOT}" "${BUNDLE_ARG}")" \
  || die "Cannot resolve bundle directory"
load_release_matrix_config "${BUNDLE_DIR}" || die "Invalid release-matrix.env"

# Allow CLI image overrides after config load
IMAGE_CU124="${IMAGE_CU124:-${RELEASE_DOCKER_IMAGE_CU124:-nvcr.io/nvidia/pytorch:24.05-py3}}"
IMAGE_CU130="${IMAGE_CU130:-${RELEASE_DOCKER_IMAGE_CU130:-nvcr.io/nvidia/pytorch:25.10-py3}}"

HOOK_RUNNER="${SCRIPT_DIR}/lib/bundle_hook_runner.sh"
PACK_SCRIPT="${SCRIPT_DIR}/pack_bundle.sh"

[[ -f "${HOOK_RUNNER}" ]] || die "Missing ${HOOK_RUNNER}"
[[ -f "${PACK_SCRIPT}" ]] || die "Missing ${PACK_SCRIPT}"
[[ -f "${DOCKER_BUILD}" ]] || die "Missing ${DOCKER_BUILD}"

resolve_flashrt_repo() {
  if [[ "${USER_REPO_ROOT}" -eq 1 ]]; then
    [[ -n "${REPO_ROOT}" ]] || die "--repo-root requires a path (or set FLASHRT_REPO)"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "DRY: use local FlashRT ${REPO_ROOT} (ref=${FLASHRT_REF})"
      REPO_ROOT="$(cd "${REPO_ROOT}" 2>/dev/null && pwd || echo "${REPO_ROOT}")"
      return 0
    fi
    local checkout_ref=""
    [[ "${USER_FLASHRT_REF}" -eq 1 ]] && checkout_ref="${FLASHRT_REF}"
    REPO_ROOT="$(ensure_flashrt_local_repo "${REPO_ROOT}" "${checkout_ref}" | tail -1)" \
      || die "Invalid --repo-root / FLASHRT_REPO"
    return 0
  fi

  if [[ "${USER_FLASHRT_GIT_URL}" -eq 1 || "${USER_FLASHRT_REF}" -eq 1 ]]; then
    REPO_ROOT="${REPO_ROOT:-${_DEFAULT_FLASHRT_DEST}}"
  else
    REPO_ROOT="${_DEFAULT_FLASHRT_DEST}"
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: clone/update FlashRT ${FLASHRT_GIT_URL} @ ${FLASHRT_REF} → ${REPO_ROOT}"
    return 0
  fi

  REPO_ROOT="$(ensure_flashrt_repo "${REPO_ROOT}" "${FLASHRT_GIT_URL}" "${FLASHRT_REF}" | tail -1)" \
    || die "Failed to prepare FlashRT at ${REPO_ROOT}"
}

resolve_flashrt_repo

if [[ "${DRY_RUN}" -eq 0 ]]; then
  REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
  [[ -f "${REPO_ROOT}/CMakeLists.txt" && -d "${REPO_ROOT}/flash_rt" ]] \
    || die "Invalid FlashRT repo: ${REPO_ROOT}"
fi

if [[ "${REPO_ROOT}" != "${WORKSPACE_ROOT}/FlashRT" && "${DRY_RUN}" -eq 0 ]]; then
  if [[ ! -e "${WORKSPACE_ROOT}/FlashRT" ]]; then
    log "Symlink ${WORKSPACE_ROOT}/FlashRT → ${REPO_ROOT}"
    ln -sfn "${REPO_ROOT}" "${WORKSPACE_ROOT}/FlashRT"
  fi
fi

image_for_cuda() {
  case "$1" in
    124) printf '%s\n' "${IMAGE_CU124}" ;;
    130) printf '%s\n' "${IMAGE_CU130}" ;;
    *) die "Unknown cuda tag: $1" ;;
  esac
}

last_cuda_tag() {
  local cuda last=""
  for cuda in ${CUDA_TAGS}; do last="${cuda}"; done
  printf '%s\n' "${last}"
}

run_docker_cuda_line() {
  local cuda="$1" image container logs_pid wait_pid ec=0
  image="$(image_for_cuda "${cuda}")"
  container="flashcli-release-${RELEASE_BUNDLE_NAME}-cu${cuda}-$$"
  log "Docker ${RELEASE_BUNDLE_NAME} cu${cuda}: ${image}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: docker run --gpus all -v ${WORKSPACE_ROOT}:/workspace ${image} cu${cuda}"
    return 0
  fi
  command -v docker >/dev/null 2>&1 || die "docker not found (use --native on Linux)"

  docker rm -f "${container}" 2>/dev/null || true

  if ! docker run -d --rm --init --gpus all \
    --name "${container}" \
    -v "${WORKSPACE_ROOT}:/workspace" \
    -e "FLASHCLI_ROOT=/workspace/flashcli" \
    -e "FLASHRT_REPO=/workspace/FlashRT" \
    -e "GIT_REF=${GIT_REF}" \
    -e "JOBS=${JOBS}" \
    -e "SM=${MATRIX_SM}" \
    -e "RELEASE_BUNDLE_NAME=${RELEASE_BUNDLE_NAME}" \
    -w /workspace/flashcli \
    "${image}" \
    bash /workspace/flashcli/scripts/lib/docker_matrix_build.sh "${cuda}"; then
    die "docker run failed for cu${cuda}"
  fi

  ACTIVE_DOCKER_CONTAINER="${container}"
  release_docker_state_register "${container}"

  docker logs -f "${container}" 2>&1 &
  logs_pid=$!
  ACTIVE_DOCKER_LOGS_PID="${logs_pid}"

  docker wait "${container}" &
  wait_pid=$!

  set +e
  wait "${wait_pid}"
  ec=$?
  set -e

  kill "${logs_pid}" 2>/dev/null || true
  wait "${logs_pid}" 2>/dev/null || true
  ACTIVE_DOCKER_LOGS_PID=""
  release_docker_state_unregister "${container}"
  ACTIVE_DOCKER_CONTAINER=""

  [[ "${ec}" -eq 0 ]] || die "Docker cu${cuda} build failed (exit ${ec})"
}

run_native_cuda_line() {
  local cuda="$1"
  log "Native ${RELEASE_BUNDLE_NAME} cu${cuda}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: build_release_matrix.sh --bundle ${RELEASE_BUNDLE_NAME} --cuda-tag ${cuda} --skip-pack"
    return 0
  fi
  export FLASHRT_REPO="${REPO_ROOT}"
  bash "${SCRIPT_DIR}/build_release_matrix.sh" \
    --bundle "${RELEASE_BUNDLE_NAME}" \
    --repo-root "${REPO_ROOT}" \
    --cuda-tag "${cuda}" \
    --git-ref "${GIT_REF}" \
    --skip-pack \
    --install-python \
    -j "${JOBS}" &
  NATIVE_PID=$!

  set +e
  wait "${NATIVE_PID}"
  local ec=$?
  set -e
  NATIVE_PID=""

  [[ "${ec}" -eq 0 ]] || die "Native cu${cuda} build failed (exit ${ec})"
}

finalize_and_pack() {
  log "Finalizing manifest + packing ${RELEASE_BUNDLE_NAME}"
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

maybe_validate() {
  [[ "${SKIP_VALIDATE}" -eq 1 ]] && return 0
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY: flashcli bundle validate ${BUNDLE_DIR}"
    return 0
  fi
  if command -v flashcli >/dev/null 2>&1; then
    flashcli bundle validate "${BUNDLE_DIR}"
    log "flashcli bundle validate OK"
  else
    log "flashcli not on PATH — pack.sh matrix/ABI checks already ran"
  fi
}

if [[ "${CLEAN}" -eq 1 ]]; then
  log "Cleaning lib/, dist/, .build-matrix/, .native-cache/"
  rm -rf \
    "${BUNDLE_DIR}/lib" \
    "${BUNDLE_DIR}/dist" \
    "${FLASHCLI_ROOT}/.build-matrix" \
    "${FLASHCLI_ROOT}/.native-cache"
fi

BUILD_CUDA_TAGS="${CUDA_TAGS}"
if [[ -n "${ONLY_CUDA}" ]]; then
  BUILD_CUDA_TAGS="${ONLY_CUDA}"
fi

if [[ "${DRY_RUN}" -eq 0 ]]; then
  install_interrupt_traps
fi

for cuda in ${BUILD_CUDA_TAGS}; do
  [[ "${cuda}" == "124" || "${cuda}" == "130" ]] || die "--cuda-tag must be 124 or 130"
  if [[ "${USE_DOCKER}" -eq 1 ]]; then
    run_docker_cuda_line "${cuda}"
  else
    [[ "$(uname -s)" == Linux ]] || die "--native requires Linux"
    run_native_cuda_line "${cuda}"
  fi
done

LAST_CUDA="$(last_cuda_tag)"
if [[ -z "${ONLY_CUDA}" || "${ONLY_CUDA}" == "${LAST_CUDA}" ]]; then
  finalize_and_pack
  maybe_validate
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    log "Release ready: ${BUNDLE_DIR}/dist/${ZIP_PREFIX}-*-sm${MATRIX_SM}-multi-linux-x86_64-*.zip"
  fi
elif [[ -n "${ONLY_CUDA}" ]]; then
  log "cu${ONLY_CUDA}-only done. Run again for remaining CUDA lines, e.g.:"
  log "  bash scripts/release_bundle.sh --bundle ${RELEASE_BUNDLE_NAME} --cuda-tag ${LAST_CUDA}"
fi
