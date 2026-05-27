#!/usr/bin/env bash
# Build / stage a Qwen model bundle (flash_rt + CUDA kernels) for flashcli serve.
#
# Usage:
#   bash flashcli/scripts/build_qwen_bundle.sh --bundle-dir flashcli/bundles/qwen_nvfp4
#   bash flashcli/scripts/build_qwen_bundle.sh --bundle-dir ... --variant qwen3 --repo-root /app/FlashRT
#   bash flashcli/scripts/build_qwen_bundle.sh --bundle-dir ... --pack-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/native_naming.sh
source "${SCRIPT_DIR}/lib/native_naming.sh"
GEN_MANIFEST="${SCRIPT_DIR}/generate_runtime_manifest.py"
BUNDLED_REQUIREMENTS="${SCRIPT_DIR}/requirements/runtime-inference.txt"

REPO_ROOT=""
BUNDLE_DIR=""
OUTPUT_DIR=""
GIT_REF="main"
RUNTIME_VERSION="1.0.0"
VARIANT="all"
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
PYTHON_BIN=""
PYTHON_MINOR=""

usage() {
  cat <<EOF
Assemble a Qwen flashcli model bundle (v2: flash_rt/ + tagged *.so at bundle root).

Usage:
  bash flashcli/scripts/build_qwen_bundle.sh --bundle-dir DIR [OPTIONS]

Required:
  --bundle-dir DIR        Bundle root (must contain flashcli-bundle.json)

Options:
  --variant NAME          qwen3 | qwen36 | all (default: all)
  --repo-root DIR         FlashRT source (default: auto-detect)
  --output-dir DIR        Also write tarball here (optional)
  --git-ref REF           Record in flashcli-bundle.json git_ref (default: main)
  --runtime-version VER   manifest runtime_version (default: 1.0.0)
  --gpu-arch ARCH         CMake -DGPU_ARCH= (default: auto SM)
  --build-dir DIR         CMake build dir (default: <repo>/build)
  -j, --jobs N            Parallel cmake jobs
  --pack-only             Skip cmake; stage existing .so
  --embed-checkpoint DIR  Copy weights into bundle checkpoint/
  --python-bin BIN        Python for manifest ABI tag (default: python3)
  --python-minor TAG      310 / 311 / 312 (default: from --python-bin)
  -h, --help

Note: Qwen3-8B NVFP4 requires SM120 (has_nvfp4). Building on SM89 produces a
runtime that will not load the NVFP4 checkpoint — use preset qwen3-8b-instruct
for RTX 4060 Ti instead.
EOF
}

log() { printf '[qwen-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Copy a source tree into dst, honoring exclude globs (rsync or tar fallback).
sync_tree() {
  local src="$1" dst="$2"
  shift 2
  local excludes=("$@")
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    local -a args=(-a)
    local pat
    for pat in "${excludes[@]}"; do
      args+=(--exclude="${pat}")
    done
    rsync "${args[@]}" "${src}/" "${dst}/"
    return 0
  fi
  log "rsync not found; using tar for ${src} -> ${dst}"
  local -a tar_args=(-C "${src}")
  local pat
  for pat in "${excludes[@]}"; do
    tar_args+=(--exclude="${pat}")
  done
  tar "${tar_args[@]}" -cf - . | tar -C "${dst}" -xf -
}

copy_dir() {
  local src="$1" dst="$2"
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${src}/" "${dst}/"
  else
    cp -a "${src}/." "${dst}/"
  fi
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
    "$(cd "${SCRIPT_DIR}/../.." && pwd)" \
    "$(cd "${SCRIPT_DIR}/../../.." && pwd)"; do
    if is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      return
    fi
  done
  die "Cannot find FlashRT repo; pass --repo-root"
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

ensure_bundle_entry_modules() {
  if [[ -f "${BUNDLE_DIR}/run.py" && -f "${BUNDLE_DIR}/serve.py" ]]; then
    return 0
  fi
  local partner_src="${BUNDLE_DIR}/partner"
  if [[ -d "${partner_src}" ]]; then
    touch "${partner_src}/__init__.py"
    return 0
  fi
  die "Missing run.py+serve.py (v2 flat) or partner/ under ${BUNDLE_DIR}"
}

stage_flash_rt_python() {
  local py_dir="$1"
  local flash_rt_src="${REPO_ROOT}/flash_rt"
  local -a excludes=(
    '*.so'
    'frontends/jax'
    'datasets'
    'refs'
    'executors/jax'
    'models/groot'
    'models/groot_n17'
    'models/pi0'
    'models/pi0fast'
    'models/motus'
    'hardware/thor'
    'frontends/torch/groot_thor.py'
    'frontends/torch/groot_rtx.py'
    'frontends/torch/pi05_thor.py'
    'frontends/torch/pi05_thor_fp4.py'
    'frontends/torch/motus'
  )
  case "${VARIANT}" in
    qwen3)
      excludes+=('models/qwen36')
      excludes+=('frontends/torch/qwen36_rtx.py')
      ;;
    qwen36)
      excludes+=('models/qwen3')
      excludes+=('frontends/torch/qwen3_rtx.py')
      ;;
    all) ;;
    *) die "Unknown --variant ${VARIANT} (use qwen3, qwen36, or all)" ;;
  esac
  sync_tree "${flash_rt_src}" "${py_dir}" "${excludes[@]}"
}

stage_qwen_serve_modules() {
  local py_dir="$1"
  local serve_dir="${py_dir}/serve"
  mkdir -p "${serve_dir}"
  touch "${serve_dir}/__init__.py"
  case "${VARIANT}" in
    qwen3|all)
      cp -f "${REPO_ROOT}/examples/qwen3_openai_server.py" \
        "${serve_dir}/qwen3_openai.py"
      ;;
  esac
  case "${VARIANT}" in
    qwen36|all)
      cp -f "${REPO_ROOT}/examples/qwen36_openai_server.py" \
        "${serve_dir}/qwen36_openai.py"
      ;;
  esac
  log "Staged OpenAI server engines -> ${serve_dir}/"
}

stage_bundle_runtime() {
  local lib_dir="${BUNDLE_DIR}"
  local py_dir="${BUNDLE_DIR}/flash_rt"
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}"
  local py_bin="${PYTHON_BIN:-python3}"

  rm -rf "${py_dir}" "${BUNDLE_DIR}/runtime"
  rm -f "${BUNDLE_DIR}"/flash_rt_*.so "${BUNDLE_DIR}"/libfmha_fp16_strided.so

  if [[ -z "${PYTHON_MINOR}" ]]; then
    PYTHON_MINOR="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"
  fi

  local git_commit flashrt_tag build_id torch_idx min_drv flashrt_abi native_tag
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  flashrt_tag="${FLASHRT_TAG:-$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)}"
  flashrt_abi="$(sanitize_flashrt_abi "${flashrt_tag}" "${git_commit}")"
  native_tag="$(native_artifact_tag "${flashrt_abi}" "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PYTHON_MINOR}")"
  local kernels_name fa2_name fp4_name
  kernels_name="$(native_so_filename flash_rt_kernels "${native_tag}")"
  fa2_name="$(native_so_filename flash_rt_fa2 "${native_tag}")"
  fp4_name="$(native_so_filename flash_rt_fp4 "${native_tag}")"
  log "Native artifact tag: ${native_tag}"
  log "  ${kernels_name}"
  log "  ${fa2_name}"
  [[ "${VARIANT}" == "qwen36" || "${VARIANT}" == "all" ]] && log "  ${fp4_name} (optional)"

  local cache_dir="${FLASHCLI_ROOT}/.native-cache/${native_tag}"
  local has_kernels=0 has_fa2=0 has_fp4=0
  rm -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}" "${lib_dir}/${fp4_name}"
  if [[ -f "${cache_dir}/${kernels_name}" ]]; then
    log "Reusing cached native libs from ${cache_dir}"
    cp -f "${cache_dir}/${kernels_name}" "${lib_dir}/"
    has_kernels=1
    [[ -f "${cache_dir}/${fa2_name}" ]] && cp -f "${cache_dir}/${fa2_name}" "${lib_dir}/" && has_fa2=1
    [[ -f "${cache_dir}/${fp4_name}" ]] && cp -f "${cache_dir}/${fp4_name}" "${lib_dir}/" && has_fp4=1
  fi
  for src in "${build_src}" "${REPO_ROOT}/flash_rt"; do
    [[ -d "${src}" ]] || continue
    normalize_lib "${src}" "${lib_dir}" "flash_rt_kernels*.so" "${kernels_name}" && has_kernels=1
    normalize_lib "${src}" "${lib_dir}" "flash_rt_fa2*.so" "${fa2_name}" && has_fa2=1
    normalize_lib "${src}" "${lib_dir}" "flash_rt_fp4*.so" "${fp4_name}" && has_fp4=1
  done

  [[ "${has_kernels}" -eq 1 ]] || die "${kernels_name} missing (build FlashRT or use --pack-only)"
  [[ "${has_fa2}" -eq 1 ]] || die "${fa2_name} missing (required for Qwen FA2 attention)"

  if [[ "${SM}" != "120" ]]; then
    log "WARNING: Qwen NVFP4 needs SM120; detected sm=${SM} — NVFP4 kernels may be absent"
  fi

  ensure_bundle_entry_modules
  stage_flash_rt_python "${py_dir}"
  stage_qwen_serve_modules "${py_dir}"
  find "${py_dir}" -name '*.so' -type f -delete 2>/dev/null || true

  build_id="${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}"
  torch_idx="$(recommended_torch_index)"
  min_drv="${MIN_DRIVER:-$(default_min_driver)}"

  log "Updating flashcli-bundle.json (v2) python_abi=${PYTHON_MINOR}"
  "${py_bin}" "${GEN_MANIFEST}" \
    --repo-root "${REPO_ROOT}" \
    --bundle-json "${BUNDLE_DIR}/flashcli-bundle.json" \
    --lib-dir "${lib_dir}" \
    --runtime-version "${RUNTIME_VERSION}" \
    --flashrt-tag "${flashrt_tag}" \
    --git-commit "${git_commit}" \
    --build-id "${build_id}" \
    --git-ref "${GIT_REF}" \
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
    --has-fmha "0" \
    --python-minor "${PYTHON_MINOR}" \
    --native-artifact-tag "${native_tag}" >/dev/null

  mkdir -p "${cache_dir}"
  cp -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}" "${cache_dir}/"
  [[ "${has_fp4}" -eq 1 ]] && cp -f "${lib_dir}/${fp4_name}" "${cache_dir}/"
  log "Cached native reuse dir: ${cache_dir}/"
}

embed_checkpoint() {
  local src="$1"
  local dest="${BUNDLE_DIR}/checkpoint"
  [[ -d "${src}" ]] || die "Checkpoint not found: ${src}"
  rm -rf "${dest}"
  copy_dir "${src}" "${dest}"
  log "Embedded checkpoint -> ${dest}"
}

maybe_write_tarball() {
  [[ -n "${OUTPUT_DIR}" ]] || return 0
  local name="flashcli-bundle-qwen-${VARIANT}-${GIT_REF}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"
  local stage="${OUTPUT_DIR}/${name}"
  mkdir -p "${OUTPUT_DIR}"
  rm -rf "${stage}"
  copy_dir "${BUNDLE_DIR}" "${stage}"
  command -v zstd >/dev/null 2>&1 || die "zstd required for tarball"
  local archive="${OUTPUT_DIR}/${name}.tar.zst"
  log "Creating ${archive}"
  tar -C "${OUTPUT_DIR}" --use-compress-program=zstd -cf "${archive}" "${name}" 2>/dev/null \
    || tar -cf - -C "${OUTPUT_DIR}" "${name}" | zstd -T0 -q -o "${archive}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
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
    --python-bin) PYTHON_BIN="$2"; shift 2 ;;
    --python-minor) PYTHON_MINOR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${BUNDLE_DIR}" ]] || { usage; die "--bundle-dir is required"; }
BUNDLE_DIR="$(cd "${BUNDLE_DIR}" && pwd)"
[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"

resolve_repo_root
ensure_runtime_requirements_file
detect_platform

if [[ "${OS_NAME}" != "linux" && "${SKIP_BUILD}" -eq 0 ]]; then
  die "Full build requires Linux; use --pack-only on macOS"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  detect_sm
  detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  command -v cmake >/dev/null 2>&1 || die "cmake not found"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found"
  run_cmake_build
else
  [[ -z "${SM}" ]] && detect_sm
  [[ -z "${CUDA_TAG}" ]] && detect_cuda_tag
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
log "  flashcli run <preset> --bundle ${BUNDLE_DIR} --model qwen3 --prompt 'Hello'"
log "  flashcli run <preset> --bundle ${BUNDLE_DIR} --model qwen36 --prompt 'Hello'"
