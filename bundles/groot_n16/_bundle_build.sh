#!/usr/bin/env bash
# Build / stage this bundle (bundles/groot_n16/_bundle_build.sh).
#
#   bash build.sh
#   bash build.sh --pack-only --repo-root /app/FlashRT
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
FLASHCLI_SCRIPTS="${FLASHCLI_ROOT}/scripts"
# shellcheck source=../../scripts/lib/native_naming.sh
source "${FLASHCLI_SCRIPTS}/lib/native_naming.sh"
# shellcheck source=../../scripts/lib/probe_native_abi.sh
source "${FLASHCLI_SCRIPTS}/lib/probe_native_abi.sh"
# shellcheck source=../../scripts/lib/manifest_overlay.sh
source "${FLASHCLI_SCRIPTS}/lib/manifest_overlay.sh"
GEN_MANIFEST="${FLASHCLI_SCRIPTS}/generate_runtime_manifest.py"
BUNDLED_REQUIREMENTS="${FLASHCLI_SCRIPTS}/requirements/runtime-inference.txt"

REPO_ROOT=""
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
FA2_NATIVE_ONLY=0
FLASHRT_TAG=""
BUILD_ID=""
MIN_DRIVER=""
CUTLASS_REF="v4.4.2"
EMBED_CHECKPOINT=""
PYTHON_BIN=""
PYTHON_MINOR=""
MERGE_NATIVE=0
SKIP_MANIFEST=0
FINALIZE_MATRIX_MANIFEST=0

usage() {
  cat <<EOF
Assemble a GROOT N1.6 flashcli model bundle (flat layout: *.so + flash_rt/ + run.py at bundle root).

Usage:
  bash bundles/groot_n16/build.sh --repo-root DIR [OPTIONS]

Options:
  --repo-root DIR         FlashRT source (default: auto-detect)
  --output-dir DIR        Also write tarball here (optional)
  --git-ref REF           Record in flashcli-bundle.json git_ref (default: main)
  --runtime-version VER   manifest runtime_version (default: 1.0.0)
  --gpu-arch ARCH         CMake -DGPU_ARCH= (default: auto SM)
  --python-bin PATH       Python for pybind build + manifest (default: python3)
  --python-minor NNN      Record python_abi 310/311/312 (default: from --python-bin)
  --sm SM                 Target SM label e.g. 120 (default: auto nvidia-smi)
  --cuda-tag TAG          Target cuda tag 130 (default: auto nvcc)
  --build-dir DIR         CMake build dir (default: <repo>/build)
  -j, --jobs N            Parallel cmake jobs
  --pack-only             Skip cmake; stage existing .so under flash_rt/ or build/
  --embed-checkpoint DIR  Copy weights into bundle checkpoint/
  --flashrt-tag TAG       manifest flashrt_tag
  --build-id ID           manifest build_id
  --min-driver VER        manifest min_driver_version
  --cutlass-branch REF    CUTLASS tag (default: v4.4.2)
  --merge-native          Install .so under lib/ (accumulate matrix cells)
  --fa2-native-only       Fast dev: FA2 sm_\${GPU_ARCH} only (not for release)
  --skip-manifest         Skip .build/manifest-overlay.json (matrix intermediate cell)
  --finalize-matrix-manifest  Scan lib/ and write multi-env manifest (after full matrix)
  -h, --help
EOF
}

log() { printf '[groot-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

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
  local -a tar_args=(-C "${src}")
  for pat in "${excludes[@]}"; do
    tar_args+=(--exclude="${pat}")
  done
  tar "${tar_args[@]}" -cf - . | tar -C "${dst}" -xf -
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
    "$(cd "${BUNDLE_DIR}/../../.." && pwd)" \
    "$(cd "${BUNDLE_DIR}/../../../.." && pwd)"; do
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
  local py_bin="${PYTHON_BIN:-python3}"
  local -a cmake_args=(
    -B "${BUILD_DIR}"
    -S "${REPO_ROOT}"
    -DGPU_ARCH="${GPU_ARCH}"
    -DPython3_EXECUTABLE="${py_bin}"
  )
  if [[ "${FA2_NATIVE_ONLY}" -eq 1 ]]; then
    cmake_args+=(-DFA2_ARCH_NATIVE_ONLY=ON)
    log "FA2: sm_${GPU_ARCH} only (FA2_ARCH_NATIVE_ONLY=ON)"
  elif [[ "${CUDA_TAG}" == "124" ]]; then
    cmake_args+=(-DFA2_ARCH_NATIVE_ONLY=ON)
    log "FA2: sm_${GPU_ARCH} AOT only for cu124"
  else
    log "FA2: multi-arch sm_80 + sm_120 + PTX (cu${CUDA_TAG})"
  fi
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

stage_groot_flash_rt_minimal() {
  local dst="$1"
  local src="${REPO_ROOT}/flash_rt"
  rm -rf "${dst}"
  mkdir -p "${dst}"

  _cp_file() {
    local rel="$1"
    mkdir -p "${dst}/$(dirname "${rel}")"
    cp -a "${src}/${rel}" "${dst}/${rel}"
  }

  for rel in __init__.py api.py models/__init__.py; do
    _cp_file "${rel}"
  done

  mkdir -p "${dst}/models/groot"
  sync_tree "${src}/models/groot" "${dst}/models/groot" 'pipeline_thor*'

  for rel in \
    frontends/__init__.py \
    frontends/torch/__init__.py \
    frontends/torch/groot_rtx.py \
    frontends/torch/groot_rtx_fp16.py; do
    _cp_file "${rel}"
  done

  _cp_file hardware/__init__.py
  [[ -f "${src}/hardware/backend.py" ]] && _cp_file hardware/backend.py

  mkdir -p "${dst}/hardware/rtx"
  for rel in attn_backend.py attn_backend_groot.py; do
    cp -a "${src}/hardware/rtx/${rel}" "${dst}/hardware/rtx/${rel}"
  done
  cat > "${dst}/hardware/rtx/__init__.py" <<'PY'
"""RTX attention backends (groot_n16 bundle subset)."""
from .attn_backend import AttnBackend, RtxFlashAttnBackend, TorchFlashAttnBackend
from .attn_backend_groot import RtxFlashAttnBackendGroot, TorchFlashAttnBackendGroot

__all__ = [
    "AttnBackend",
    "RtxFlashAttnBackend",
    "TorchFlashAttnBackend",
    "RtxFlashAttnBackendGroot",
    "TorchFlashAttnBackendGroot",
]
PY

  mkdir -p "${dst}/core"
  sync_tree "${src}/core" "${dst}/core" '*.so' 'rl'

  mkdir -p "${dst}/executors"
  for rel in __init__.py torch_weights.py weight_loader.py; do
    [[ -f "${src}/executors/${rel}" ]] && cp -a "${src}/executors/${rel}" "${dst}/executors/${rel}"
  done

  mkdir -p "${dst}/utils"
  sync_tree "${src}/utils" "${dst}/utils"

  log "Staged minimal flash_rt/ for groot_n16 ($(find "${dst}" -type f | wc -l) files)"
}

finalize_matrix_manifest() {
  local native_lib="${BUNDLE_DIR}/lib"
  local scan_dir="${native_lib}"
  if [[ ! -d "${scan_dir}" ]] || ! compgen -G "${scan_dir}"/*.so >/dev/null; then
    scan_dir="${BUNDLE_DIR}/runtime"
    [[ -d "${scan_dir}" ]] || die "Missing lib/ or runtime/ for --finalize-matrix-manifest"
  fi
  local py_bin="${PYTHON_BIN:-python3}"
  log "Finalizing multi-env manifest overlay from ${scan_dir}"
  run_manifest_overlay "${BUNDLE_DIR}" "${scan_dir}" "${GEN_MANIFEST}" "${REPO_ROOT}" "${py_bin}" \
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
    --has-fp4 "0" \
    --has-fmha "0" \
    --python-minor "312" >/dev/null
}

stage_bundle_runtime() {
  local py_dir="${BUNDLE_DIR}/flash_rt"
  local flash_rt_src="${REPO_ROOT}/flash_rt"
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}/native-out"
  local skip_py_stage=0
  local lib_dir env_key runtime_cell

  if [[ "${MERGE_NATIVE}" -eq 1 ]]; then
    lib_dir="${BUNDLE_DIR}/lib"
    mkdir -p "${lib_dir}"
  else
    local py_bin_probe="${PYTHON_BIN:-python3}"
    if [[ -z "${PYTHON_MINOR}" ]]; then
      PYTHON_MINOR="$("${py_bin_probe}" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"
    fi
    env_key="$(runtime_env_key "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PYTHON_MINOR}")"
    runtime_cell="${BUNDLE_DIR}/runtime/${env_key}"
    mkdir -p "${runtime_cell}"
    lib_dir="${runtime_cell}"
    log "Staging native .so -> runtime/${env_key}/"
    shopt -s nullglob
    for legacy_so in "${BUNDLE_DIR}"/flash_rt_*.so; do
      [[ -f "${legacy_so}" ]] || continue
      log "Moving legacy $(basename "${legacy_so}") -> runtime/${env_key}/"
      mv -f "${legacy_so}" "${runtime_cell}/"
    done
    shopt -u nullglob
  fi

  if [[ "${MERGE_NATIVE}" -eq 1 && -d "${py_dir}" && -f "${py_dir}/api.py" ]]; then
    skip_py_stage=1
    log "Keeping existing flash_rt/ (--merge-native matrix cell)"
  else
    rm -rf "${py_dir}"
  fi
  if [[ "${MERGE_NATIVE}" -eq 0 ]]; then
    rm -rf "${BUNDLE_DIR}/lib"
  fi
  rm -f "${BUNDLE_DIR}"/flash_rt_*.so "${BUNDLE_DIR}"/libfmha_fp16_strided.so

  local py_bin="${PYTHON_BIN:-python3}"
  if [[ -z "${PYTHON_MINOR}" ]]; then
    PYTHON_MINOR="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"
  fi
  if [[ "${MERGE_NATIVE}" -eq 0 && -z "${env_key:-}" ]]; then
    env_key="$(runtime_env_key "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PYTHON_MINOR}")"
    runtime_cell="${BUNDLE_DIR}/runtime/${env_key}"
    mkdir -p "${runtime_cell}"
    lib_dir="${runtime_cell}"
  fi

  local git_commit flashrt_tag build_id torch_idx min_drv flashrt_abi native_tag
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  flashrt_tag="${FLASHRT_TAG:-$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)}"
  flashrt_abi="$(sanitize_flashrt_abi "${flashrt_tag}" "${git_commit}")"
  native_tag="$(native_artifact_tag "${flashrt_abi}" "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PYTHON_MINOR}")"
  local kernels_name fa2_name
  kernels_name="$(native_so_filename flash_rt_kernels "${native_tag}")"
  fa2_name="$(native_so_filename flash_rt_fa2 "${native_tag}")"
  log "Native artifact tag: ${native_tag}"
  log "  ${kernels_name}"
  log "  ${fa2_name}"

  local cache_dir="${FLASHCLI_ROOT}/.native-cache/${native_tag}"
  local has_kernels=0 has_fa2=0
  rm -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}"
  if [[ -f "${cache_dir}/${kernels_name}" && -f "${cache_dir}/${fa2_name}" ]]; then
    log "Reusing cached native libs from ${cache_dir}"
    cp -f "${cache_dir}/${kernels_name}" "${cache_dir}/${fa2_name}" "${lib_dir}/"
    has_kernels=1
    has_fa2=1
  fi
  if [[ ! -d "${build_src}" ]] || ! compgen -G "${build_src}"/*.so >/dev/null; then
    build_src="${flash_rt_src}"
    log "Using ${build_src} for native staging (--pack-only or missing native-out)"
  fi
  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_kernels "${kernels_name}" \
    "${PYTHON_MINOR}" && has_kernels=1
  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_fa2 "${fa2_name}" \
    "${PYTHON_MINOR}" && has_fa2=1

  [[ "${has_kernels}" -eq 1 ]] || die "${kernels_name} missing (build FlashRT or use --pack-only)"
  [[ "${has_fa2}" -eq 1 ]] || die "${fa2_name} missing (required for GROOT FA2 attention)"

  _verify_staged_native_abi() {
    local name="$1"
    local so="${lib_dir}/${name}"
    [[ -f "${so}" ]] || return 0
    local rc=0 err=""
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

  if [[ "${skip_py_stage}" -eq 0 ]]; then
    stage_groot_flash_rt_minimal "${py_dir}"
    find "${py_dir}" -name '*.so' -type f -delete 2>/dev/null || true
  fi

  build_id="${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}"
  torch_idx="$(recommended_torch_index)"
  min_drv="${MIN_DRIVER:-$(default_min_driver)}"

  if [[ "${SKIP_MANIFEST}" -eq 1 ]]; then
    log "Skipping manifest overlay (--skip-manifest)"
    mkdir -p "${FLASHCLI_ROOT}/.native-cache/${native_tag}"
    cp -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}" \
      "${FLASHCLI_ROOT}/.native-cache/${native_tag}/"
    return 0
  fi

  local overlay_scan_dir="${lib_dir}"
  if [[ "${MERGE_NATIVE}" -eq 0 ]]; then
    overlay_scan_dir="${BUNDLE_DIR}/runtime"
  fi
  run_manifest_overlay "${BUNDLE_DIR}" "${overlay_scan_dir}" "${GEN_MANIFEST}" "${REPO_ROOT}" "${py_bin}" \
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
    --has-fp4 "0" \
    --has-fmha "0" \
    --python-minor "${PYTHON_MINOR}" \
    --native-artifact-tag "${native_tag}" >/dev/null
  log "Cached native reuse dir: ${FLASHCLI_ROOT}/.native-cache/${native_tag}/"
  mkdir -p "${FLASHCLI_ROOT}/.native-cache/${native_tag}"
  cp -f "${lib_dir}/${kernels_name}" "${lib_dir}/${fa2_name}" \
    "${FLASHCLI_ROOT}/.native-cache/${native_tag}/"
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
  local py_suffix=""
  if [[ -n "${PYTHON_MINOR}" ]]; then
    py_suffix="-py${PYTHON_MINOR}"
  fi
  local name="flashcli-bundle-groot-n16-${GIT_REF}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}${py_suffix}"
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
    --python-bin) PYTHON_BIN="$2"; shift 2 ;;
    --python-minor) PYTHON_MINOR="$2"; shift 2 ;;
    --sm) SM="$2"; shift 2 ;;
    --cuda-tag) CUDA_TAG="$2"; shift 2 ;;
    --merge-native) MERGE_NATIVE=1; shift ;;
    --fa2-native-only) FA2_NATIVE_ONLY=1; shift ;;
    --skip-manifest) SKIP_MANIFEST=1; shift ;;
    --finalize-matrix-manifest) FINALIZE_MATRIX_MANIFEST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing ${BUNDLE_DIR}/flashcli-bundle.json"

if [[ "${FINALIZE_MATRIX_MANIFEST}" -eq 1 ]]; then
  resolve_repo_root
  detect_platform
  [[ -n "${SM}" ]] || SM="120"
  finalize_matrix_manifest
  log "Matrix manifest ready: ${BUNDLE_DIR}/flashcli-bundle.json"
  exit 0
fi

resolve_repo_root
ensure_runtime_requirements_file
detect_platform

if [[ "${OS_NAME}" != "linux" && "${SKIP_BUILD}" -eq 0 ]]; then
  die "Full build requires Linux; use --pack-only on macOS after copying .so from a GPU build"
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  [[ -n "${SM}" ]] || detect_sm
  [[ -n "${CUDA_TAG}" ]] || detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  command -v cmake >/dev/null 2>&1 || die "cmake not found"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found"
  run_cmake_build
  stage_bundle_runtime
else
  [[ -n "${SM}" ]] || detect_sm
  [[ -n "${CUDA_TAG}" ]] || detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  log "Skipping cmake (--pack-only)"
  stage_bundle_runtime
fi

if [[ -n "${EMBED_CHECKPOINT}" ]]; then
  embed_checkpoint "${EMBED_CHECKPOINT}"
fi

maybe_write_tarball

log "Bundle ready: ${BUNDLE_DIR}"
if [[ "${MERGE_NATIVE}" -eq 0 && -n "${env_key:-}" ]]; then
  log "  runtime/${env_key}/ ($(find "${BUNDLE_DIR}/runtime/${env_key}" -name '*.so' 2>/dev/null | wc -l | tr -d ' ') .so)"
fi
log "  bash bundles/groot_n16/pack.sh"
log "  flashcli bundle validate ${BUNDLE_DIR}/dist"
