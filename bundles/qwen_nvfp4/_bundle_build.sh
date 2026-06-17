#!/usr/bin/env bash
# Build / stage this bundle (bundles/qwen_nvfp4/_bundle_build.sh).
#
#   bash build.sh --repo-root /app/FlashRT
#   bash matrix_cell.sh ...          # release matrix
#   bash finalize_manifest.sh ...
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
FLASHCLI_SCRIPTS="${FLASHCLI_ROOT}/scripts"
# shellcheck source=../../scripts/lib/native_naming.sh
source "${FLASHCLI_SCRIPTS}/lib/native_naming.sh"
# shellcheck source=../../scripts/lib/probe_native_abi.sh
source "${FLASHCLI_SCRIPTS}/lib/probe_native_abi.sh"
GEN_MANIFEST="${FLASHCLI_SCRIPTS}/generate_runtime_manifest.py"
BUNDLED_REQUIREMENTS="${FLASHCLI_SCRIPTS}/requirements/runtime-inference.txt"

REPO_ROOT=""
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
MERGE_NATIVE=0
SKIP_MANIFEST=0
FINALIZE_MATRIX_MANIFEST=0
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
Assemble a Qwen flashcli model bundle (v2: flash_rt/ + tagged *.so under lib/).

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
  --sm SM                 SM label (default: auto from GPU; release matrix uses 120)
  --cuda-tag TAG          CUDA tag 124 / 130 (default: from nvcc)
  --merge-native          Stage .so into lib/ without replacing other matrix cells
  --skip-manifest         Skip flashcli-bundle.json update (matrix intermediate cell)
  --finalize-matrix-manifest  After full matrix, scan lib/ and write multi-env manifest
  -h, --help

Note: Qwen NVFP4 requires SM120. Release: bash release.sh or scripts/release_bundle.sh --bundle qwen_nvfp4.
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
  local py_bin="${PYTHON_BIN:-python3}"
  local -a cmake_args=(
    -B "${BUILD_DIR}"
    -S "${REPO_ROOT}"
    -DGPU_ARCH="${GPU_ARCH}"
    -DPython3_EXECUTABLE="${py_bin}"
  )
  if [[ "${FA2_NATIVE_ONLY}" -eq 1 ]]; then
    cmake_args+=(-DFA2_ARCH_NATIVE_ONLY=ON)
  fi
  # FlashRT writes pybind .so into ${REPO_ROOT}/flash_rt/ (shared). Clear stale ABIs.
  clean_flashrt_shared_native_outputs "${REPO_ROOT}"
  log "CMake configure GPU_ARCH=${GPU_ARCH} Python3_EXECUTABLE=${py_bin} ($("${py_bin}" --version 2>&1 | head -1))"
  cmake "${cmake_args[@]}"
  cmake --build "${BUILD_DIR}" -j"${JOBS}"
  snapshot_flashrt_native_to_build_dir "${REPO_ROOT}" "${BUILD_DIR}"
  shopt -s nullglob
  local so
  for so in "${BUILD_DIR}/native-out"/flash_rt_kernels*.so; do
    [[ -f "${so}" ]] || continue
    log "Built native: $(basename "${so}")"
    break
  done
  shopt -u nullglob
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
      [[ -d "${REPO_ROOT}/serving/qwen36_agent" ]] \
        || die "Missing ${REPO_ROOT}/serving/qwen36_agent (update FlashRT for agent serving)"
      rm -rf "${serve_dir}/qwen36_agent"
      cp -a "${REPO_ROOT}/serving/qwen36_agent" "${serve_dir}/qwen36_agent"
      rm -f "${serve_dir}/qwen36_openai.py"
      ;;
  esac
  log "Staged serve engines -> ${serve_dir}/"
}

finalize_matrix_manifest() {
  local native_lib="${BUNDLE_DIR}/lib"
  [[ -d "${native_lib}" ]] || die "Missing ${native_lib} for --finalize-matrix-manifest"
  local py_bin="${PYTHON_BIN:-python3}"
  log "Finalizing multi-env manifest from ${native_lib}"
  "${py_bin}" "${GEN_MANIFEST}" \
    --repo-root "${REPO_ROOT}" \
    --bundle-json "${BUNDLE_DIR}/flashcli-bundle.json" \
    --lib-dir "${native_lib}" \
    --matrix-manifest \
    --runtime-version "${RUNTIME_VERSION}" \
    --flashrt-tag "${FLASHRT_TAG:-dev}" \
    --git-commit "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)" \
    --build-id "${BUILD_ID:-matrix}" \
    --git-ref "${GIT_REF}" \
    --sm "${SM:-120}" \
    --os-name "${OS_NAME:-linux}" \
    --cpuarch "${CPU_ARCH:-x86_64}" \
    --gpu-arch "${GPU_ARCH:-120}" \
    --cuda-tag "${CUDA_TAG:-130}" \
    --toolkit "13.0" \
    --torch-index "cu128" \
    --min-driver "550.54.14" \
    --has-fa2 "1" \
    --has-fp4 "1" \
    --has-fmha "0" \
    --python-minor "310" >/dev/null
}

stage_bundle_runtime() {
  local lib_dir="${BUNDLE_DIR}/lib"
  local py_dir="${BUNDLE_DIR}/flash_rt"
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}/native-out"
  local py_bin="${PYTHON_BIN:-python3}"
  local skip_py_stage=0

  mkdir -p "${lib_dir}"
  if [[ "${MERGE_NATIVE}" -eq 1 && -d "${py_dir}" && -f "${py_dir}/api.py" ]]; then
    skip_py_stage=1
    log "Keeping existing flash_rt/ (--merge-native)"
  else
    rm -rf "${py_dir}"
  fi
  rm -rf "${BUNDLE_DIR}/runtime"
  # v2 spec: native *.so live under lib/ only (not bundle root).
  rm -f "${BUNDLE_DIR}"/flash_rt_*.so "${BUNDLE_DIR}"/libfmha_fp16_strided.so
  for legacy_so in "${BUNDLE_DIR}"/flash_rt_*.so "${BUNDLE_DIR}"/libfmha_fp16_strided.so; do
    [[ -f "${legacy_so}" ]] || continue
    log "Moving legacy $(basename "${legacy_so}") -> lib/"
    mv -f "${legacy_so}" "${lib_dir}/"
  done

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
  if [[ ! -d "${build_src}" ]] || ! compgen -G "${build_src}"/*.so >/dev/null; then
    build_src="${REPO_ROOT}/flash_rt"
    log "Using ${build_src} for native staging (--pack-only or missing native-out)"
  fi
  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_kernels "${kernels_name}" \
    "${PYTHON_MINOR}" && has_kernels=1
  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_fa2 "${fa2_name}" \
    "${PYTHON_MINOR}" && has_fa2=1
  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_fp4 "${fp4_name}" \
    "${PYTHON_MINOR}" && has_fp4=1

  [[ "${has_kernels}" -eq 1 ]] || die "${kernels_name} missing (build FlashRT or use --pack-only)"
  [[ "${has_fa2}" -eq 1 ]] || die "${fa2_name} missing (required for Qwen FA2 attention)"
  # SM120 Qwen NVFP4 is compiled into flash_rt_kernels (CUTLASS sm_120a).
  # flash_rt_fp4.so is a separate Thor/SM100 add-on (CMake ENABLE_SM100_CUTLASS only).
  if [[ "${has_fp4}" -eq 0 ]]; then
    if [[ "${SM}" == "120" ]]; then
      log "flash_rt_fp4.so not built (expected on SM120 — NVFP4 is in ${kernels_name})"
    else
      die "${fp4_name} missing (flash_rt_fp4 required when sm != 120)"
    fi
  fi
  local nvfp4_feature=0
  if [[ "${SM}" == "120" && "${has_kernels}" -eq 1 ]]; then
    nvfp4_feature=1
  elif [[ "${has_fp4}" -eq 1 ]]; then
    nvfp4_feature=1
  fi

  if [[ "${SM}" != "120" ]]; then
    log "WARNING: Qwen NVFP4 needs SM120; detected sm=${SM}"
  fi

  _verify_staged_native_abi() {
    local name="$1"
    local so="${lib_dir}/${name}"
    [[ -f "${so}" ]] || return 0
    local rc=0
    local err=""
    err="$(probe_native_so_python_abi "${py_bin}" "${so}" 2>&1)" || rc=$?
    if [[ "${rc}" -eq 2 ]]; then
      die \
        "${name}: Python ABI mismatch (expected -py${PYTHON_MINOR}, built with another Python). " \
        "Use matching --python-bin, rm -rf '${BUILD_DIR:-${REPO_ROOT}/build}', rebuild. Detail: ${err}"
    fi
    if [[ "${rc}" -ne 0 ]]; then
      log "WARN: ${name} did not fully import under ${py_bin} (rc=${rc}); continuing (often missing CUDA at build time)"
    else
      log "ABI OK: ${name} loads under ${py_bin}"
    fi
  }
  _verify_staged_native_abi "${kernels_name}"
  _verify_staged_native_abi "${fa2_name}"
  [[ "${has_fp4}" -eq 1 ]] && _verify_staged_native_abi "${fp4_name}"

  ensure_bundle_entry_modules
  if [[ "${skip_py_stage}" -eq 0 ]]; then
    stage_flash_rt_python "${py_dir}"
    stage_qwen_serve_modules "${py_dir}"
    find "${py_dir}" -name '*.so' -type f -delete 2>/dev/null || true
  fi

  build_id="${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}"
  torch_idx="$(recommended_torch_index)"
  min_drv="${MIN_DRIVER:-$(default_min_driver)}"

  if [[ "${SKIP_MANIFEST}" -eq 1 ]]; then
    log "Skipping manifest update (--skip-manifest)"
    mkdir -p "${cache_dir}"
    cp -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}" "${cache_dir}/"
    [[ "${has_fp4}" -eq 1 ]] && cp -f "${lib_dir}/${fp4_name}" "${cache_dir}/"
    return 0
  fi

  log "Updating flashcli-bundle.json (v2, lib/) python_abi=${PYTHON_MINOR}"
  "${py_bin}" "${GEN_MANIFEST}" \
    --repo-root "${REPO_ROOT}" \
    --bundle-json "${BUNDLE_DIR}/flashcli-bundle.json" \
    --lib-dir "${lib_dir}" \
    --matrix-manifest \
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
    --has-fp4 "${nvfp4_feature}" \
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
    --sm) SM="$2"; shift 2 ;;
    --cuda-tag) CUDA_TAG="$2"; shift 2 ;;
    --merge-native) MERGE_NATIVE=1; shift ;;
    --skip-manifest) SKIP_MANIFEST=1; shift ;;
    --finalize-matrix-manifest) FINALIZE_MATRIX_MANIFEST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"

if [[ "${FINALIZE_MATRIX_MANIFEST}" -eq 1 ]]; then
  resolve_repo_root
  detect_platform
  SM="${SM:-120}"
  finalize_matrix_manifest
  log "Matrix manifest ready: ${BUNDLE_DIR}/flashcli-bundle.json"
  exit 0
fi

resolve_repo_root
ensure_runtime_requirements_file
detect_platform

if [[ "${OS_NAME}" != "linux" && "${SKIP_BUILD}" -eq 0 ]]; then
  die "Full build requires Linux; use --pack-only on macOS"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  [[ -n "${SM}" ]] || detect_sm
  [[ -n "${CUDA_TAG}" ]] || detect_cuda_tag
  if [[ "${CUDA_TAG}" == "124" ]]; then
    die "qwen_nvfp4 (SM120/NVFP4) cannot build cu124: nvcc 12.4 lacks sm_120/sm_120a. Use cu130 only (25.10-py3 container or --cuda-tag 130)."
  fi
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
log "  flashcli run ${BUNDLE_DIR}@qwen3 --prompt 'Hello'"
log "  flashcli serve ${BUNDLE_DIR}@qwen3"
log "  Release: cd bundles/qwen_nvfp4 && bash release.sh"
