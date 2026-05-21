#!/usr/bin/env bash
# Build / stage a Pi0.5 model bundle (flash_rt + CUDA kernels) for flashcli run.
#
# Usage:
#   bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir flashcli/bundles/pi05_libero
#   bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir ... --repo-root /app/FlashRT
#   bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir ... --pack-only
#   bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir ... --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GEN_MANIFEST="${SCRIPT_DIR}/generate_runtime_manifest.py"
BUNDLED_REQUIREMENTS="${SCRIPT_DIR}/requirements/runtime-inference.txt"

REPO_ROOT=""
BUNDLE_DIR=""
OUTPUT_DIR=""
GIT_REF="main"
RUNTIME_VERSION="1.0.0"
SM=""
CUDA_TAG=""
OS_NAME=""
CPU_ARCH=""
GPU_ARCH=""
BUILD_DIR=""
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
SKIP_BUILD=0
FA2_NATIVE_ONLY=1
FLASHRT_TAG=""
BUILD_ID=""
MIN_DRIVER=""
CUTLASS_REF="v4.4.2"
EMBED_CHECKPOINT=""

usage() {
  cat <<EOF
Assemble a Pi0.5 flashcli model bundle (runtime/lib + runtime/python/flash_rt).

Usage:
  bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir DIR [OPTIONS]

Required:
  --bundle-dir DIR        Bundle root (must contain flashcli-bundle.json)

Options:
  --repo-root DIR         FlashRT source (default: auto-detect)
  --output-dir DIR        Also write tarball here (optional)
  --git-ref REF           Record in flashcli-bundle.json git_ref (default: main)
  --runtime-version VER   manifest runtime_version (default: 1.0.0)
  --gpu-arch ARCH         CMake -DGPU_ARCH= (default: auto SM)
  --build-dir DIR         CMake build dir (default: <repo>/build)
  -j, --jobs N            Parallel cmake jobs
  --pack-only             Skip cmake; stage existing .so under flash_rt/ or build/
  --embed-checkpoint DIR  Copy weights into bundle checkpoint/
  --flashrt-tag TAG       manifest flashrt_tag
  --build-id ID           manifest build_id
  --min-driver VER        manifest min_driver_version
  --cutlass-branch REF    CUTLASS tag (default: v4.4.2)
  -h, --help
EOF
}

log() { printf '[pi05-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

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
    "$(cd "${SCRIPT_DIR}/../.." && pwd)" \
    "$(cd "${SCRIPT_DIR}/../../.." && pwd)"; do
    if is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      return
    fi
  done
  die "Cannot find FlashRT repo; pass --repo-root (need CMakeLists.txt + flash_rt/)"
}

ensure_runtime_requirements_file() {
  local dest="${REPO_ROOT}/requirements/runtime-inference.txt"
  if [[ -f "${dest}" ]]; then
    return 0
  fi
  [[ -f "${BUNDLED_REQUIREMENTS}" ]] || die "Missing ${BUNDLED_REQUIREMENTS}"
  mkdir -p "${REPO_ROOT}/requirements"
  cp -f "${BUNDLED_REQUIREMENTS}" "${dest}"
}

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
  die "nvcc not found (required on build host)"
}

detect_sm() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    local cc
    cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
    [[ -n "${cc}" ]] || die "nvidia-smi returned empty compute_cap"
    SM="${cc//./}"
    log "sm=${SM} (compute_cap=${cc})"
    return
  fi
  die "nvidia-smi not found"
}

detect_platform() {
  case "$(uname -s)" in
    Linux) OS_NAME="linux" ;;
    Darwin) OS_NAME="macos" ;;
    MINGW*|MSYS*|CYGWIN*) OS_NAME="win" ;;
    *) OS_NAME="linux" ;;
  esac
  CPU_ARCH="$(uname -m)"
  case "${CPU_ARCH}" in
    amd64|x64) CPU_ARCH="x86_64" ;;
  esac
}

recommended_torch_index() {
  case "${CUDA_TAG}" in
    128|130) echo "cu128" ;;
    *) echo "cu124" ;;
  esac
}

cuda_toolkit_version() {
  case "${CUDA_TAG}" in
    124) echo "12.4" ;;
    128) echo "12.8" ;;
    130) echo "13.0" ;;
    *) echo "${CUDA_TAG:0:1}.${CUDA_TAG:1}" ;;
  esac
}

default_min_driver() {
  case "${CUDA_TAG}" in
    128|130) echo "550.54.14" ;;
    *) echo "525.60.13" ;;
  esac
}

ensure_cutlass() {
  local cutlass_dir="${REPO_ROOT}/third_party/cutlass"
  if [[ -d "${cutlass_dir}/include" ]]; then
    return
  fi
  log "Cloning CUTLASS ${CUTLASS_REF}"
  mkdir -p "${REPO_ROOT}/third_party"
  git clone --depth 1 --branch "${CUTLASS_REF}" \
    https://github.com/NVIDIA/cutlass.git "${cutlass_dir}"
}

run_cmake_build() {
  ensure_cutlass
  BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"
  local -a cmake_args=(
    -B "${BUILD_DIR}"
    -S "${REPO_ROOT}"
    -DGPU_ARCH="${GPU_ARCH}"
  )
  if [[ "${FA2_NATIVE_ONLY}" -eq 1 ]]; then
    cmake_args+=(-DFA2_ARCH_NATIVE_ONLY=ON)
  fi
  log "CMake configure GPU_ARCH=${GPU_ARCH}"
  cmake "${cmake_args[@]}"
  cmake --build "${BUILD_DIR}" -j"${JOBS}"
  shopt -s nullglob
  local so
  for so in "${BUILD_DIR}"/flash_rt_kernels*.so "${BUILD_DIR}"/flash_rt_fa2*.so; do
    cp -f "${so}" "${REPO_ROOT}/flash_rt/"
  done
  shopt -u nullglob
}

normalize_lib() {
  local src_dir="$1" dst_lib="$2" pattern="$3" dest_name="$4"
  shopt -s nullglob
  local matches=("${src_dir}"/${pattern})
  shopt -u nullglob
  if [[ ${#matches[@]} -eq 0 ]]; then
    return 1
  fi
  cp -f "${matches[0]}" "${dst_lib}/${dest_name}"
}

stage_partner_python() {
  local py_root="$1"
  local partner_src="${BUNDLE_DIR}/partner"
  [[ -d "${partner_src}" ]] || return 0
  mkdir -p "${py_root}"
  rsync -a "${partner_src}/" "${py_root}/partner/"
  log "Staged partner/ -> ${py_root}/partner/"
}

stage_flash_rt_python() {
  local py_dir="$1"
  local flash_rt_src="${REPO_ROOT}/flash_rt"
  command -v rsync >/dev/null 2>&1 || die "rsync required"
  local -a excludes=(
    --exclude='*.so'
    --exclude='frontends/jax'
    --exclude='serve'
    --exclude='datasets'
    --exclude='refs'
    --exclude='executors/jax'
    --exclude='configs'
    --exclude='models/groot'
    --exclude='models/groot_n17'
    --exclude='models/pi0'
    --exclude='models/pi0fast'
    --exclude='models/qwen3'
    --exclude='models/qwen36'
    --exclude='frontends/torch/qwen3_rtx.py'
    --exclude='frontends/torch/qwen36_rtx.py'
    --exclude='hardware/thor'
  )
  mkdir -p "${py_dir}"
  rsync -a "${excludes[@]}" "${flash_rt_src}/" "${py_dir}/"
}

stage_bundle_runtime() {
  local runtime_dir="${BUNDLE_DIR}/runtime"
  local lib_dir="${runtime_dir}/lib"
  local py_dir="${runtime_dir}/python/flash_rt"
  local flash_rt_src="${REPO_ROOT}/flash_rt"
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}"

  rm -rf "${lib_dir}" "${py_dir}"
  mkdir -p "${lib_dir}"

  # Prefer cmake output over committed flash_rt/*.so (may be stale).
  local has_kernels=0 has_fa2=0 has_fp4=0 has_fmha=0
  for src in "${build_src}" "${flash_rt_src}"; do
    [[ -d "${src}" ]] || continue
    normalize_lib "${src}" "${lib_dir}" "flash_rt_kernels*.so" "flash_rt_kernels.so" && has_kernels=1
    normalize_lib "${src}" "${lib_dir}" "flash_rt_fa2*.so" "flash_rt_fa2.so" && has_fa2=1
    normalize_lib "${src}" "${lib_dir}" "flash_rt_fp4*.so" "flash_rt_fp4.so" && has_fp4=1
    normalize_lib "${src}" "${lib_dir}" "libfmha_fp16_strided*.so" "libfmha_fp16_strided.so" && has_fmha=1
    normalize_lib "${src}" "${lib_dir}" "fmha_fp16_strided*.so" "libfmha_fp16_strided.so" && has_fmha=1
  done

  [[ "${has_kernels}" -eq 1 ]] || die "flash_rt_kernels.so missing (build FlashRT or use --pack-only after cmake)"

  stage_flash_rt_python "${py_dir}"
  stage_partner_python "$(dirname "${py_dir}")"
  find "${py_dir}" -name '*.so' -type f -delete 2>/dev/null || true

  local git_commit flashrt_tag build_id torch_idx min_drv
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  flashrt_tag="${FLASHRT_TAG:-$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)}"
  build_id="${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}"
  torch_idx="$(recommended_torch_index)"
  min_drv="${MIN_DRIVER:-$(default_min_driver)}"

  log "Writing runtime/manifest.json"
  python3 "${GEN_MANIFEST}" \
    --repo-root "${REPO_ROOT}" \
    --stage-root "${runtime_dir}" \
    --lib-dir "${lib_dir}" \
    --runtime-version "${RUNTIME_VERSION}" \
    --flashrt-tag "${flashrt_tag}" \
    --git-commit "${git_commit}" \
    --build-id "${build_id}" \
    --sm "${SM}" \
    --os-name "${OS_NAME}" \
    --cpuarch "${CPU_ARCH}" \
    --gpu-arch "${GPU_ARCH}" \
    --cuda-tag "${CUDA_TAG}" \
    --toolkit "$(cuda_toolkit_version)" \
    --torch-index "${torch_idx}" \
    --min-driver "${min_drv}" \
    --has-fa2 "${has_fa2}" \
    --has-fp4 "${has_fp4}" \
    --has-fmha "${has_fmha}" >/dev/null

  python3 - "${BUNDLE_DIR}/flashcli-bundle.json" "${runtime_dir}/manifest.json" "${GIT_REF}" <<'PY'
import json
import sys
from pathlib import Path

bundle_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
git_ref = sys.argv[3]
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
bundle["git_ref"] = git_ref
bundle["native_libs"] = {
    "flashrt_tag": manifest.get("flashrt_tag"),
    "build_id": manifest.get("build_id"),
    "git_commit": manifest.get("git_commit"),
    "modules": manifest.get("modules", []),
}
bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
PY
}

embed_checkpoint() {
  local src="$1"
  local dest="${BUNDLE_DIR}/checkpoint"
  [[ -d "${src}" ]] || die "Checkpoint not found: ${src}"
  rm -rf "${dest}"
  mkdir -p "${dest}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${src}/" "${dest}/"
  else
    cp -a "${src}/." "${dest}/"
  fi
  log "Embedded checkpoint -> ${dest}"
}

maybe_write_tarball() {
  [[ -n "${OUTPUT_DIR}" ]] || return 0
  local name="flashcli-bundle-pi05-${GIT_REF}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"
  local stage="${OUTPUT_DIR}/${name}"
  mkdir -p "${OUTPUT_DIR}"
  rm -rf "${stage}"
  mkdir -p "${stage}"
  rsync -a "${BUNDLE_DIR}/" "${stage}/"
  command -v zstd >/dev/null 2>&1 || die "zstd required for tarball (--output-dir)"
  local archive="${OUTPUT_DIR}/${name}.tar.zst"
  log "Creating ${archive}"
  tar -C "${OUTPUT_DIR}" --use-compress-program=zstd -cf "${archive}" "${name}" 2>/dev/null \
    || tar -cf - -C "${OUTPUT_DIR}" "${name}" | zstd -T0 -q -o "${archive}"
  log "Tarball: ${archive}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    --runtime-version) RUNTIME_VERSION="$2"; shift 2 ;;
    --gpu-arch) GPU_ARCH="$2"; shift 2 ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    -j|--jobs) JOBS="$2"; shift 2 ;;
    --pack-only|--skip-build) SKIP_BUILD=1; shift ;;
    --embed-checkpoint) EMBED_CHECKPOINT="$2"; shift 2 ;;
    --flashrt-tag) FLASHRT_TAG="$2"; shift 2 ;;
    --build-id) BUILD_ID="$2"; shift 2 ;;
    --min-driver) MIN_DRIVER="$2"; shift 2 ;;
    --cutlass-branch) CUTLASS_REF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${BUNDLE_DIR}" ]] || { usage; die "--bundle-dir is required"; }
BUNDLE_DIR="$(cd "${BUNDLE_DIR}" && pwd)"
[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing ${BUNDLE_DIR}/flashcli-bundle.json"

resolve_repo_root
ensure_runtime_requirements_file
detect_platform

if [[ "${OS_NAME}" != "linux" && "${SKIP_BUILD}" -eq 0 ]]; then
  die "Full build requires Linux; use --pack-only on macOS after copying .so from a GPU build"
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  detect_sm
  detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  command -v cmake >/dev/null 2>&1 || die "cmake not found"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found"
  run_cmake_build
else
  if [[ -z "${SM}" ]]; then detect_sm; fi
  if [[ -z "${CUDA_TAG}" ]]; then detect_cuda_tag; fi
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  log "Skipping cmake (--pack-only)"
fi

stage_bundle_runtime

if [[ -n "${EMBED_CHECKPOINT}" ]]; then
  embed_checkpoint "${EMBED_CHECKPOINT}"
fi

maybe_write_tarball

log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
log "  flashcli run pi05_libero --bundle ${BUNDLE_DIR}"
