#!/usr/bin/env bash
# wan22 bundle build hooks — implements the flashcli release contract.
#
#   matrix cell : bash _bundle_build.sh --repo-root D --python-bin P --python-minor NNN \
#                   --sm SM --cuda-tag TAG --build-dir D --git-ref R -j N [--merge-native]
#   finalize    : bash _bundle_build.sh --finalize-matrix-manifest --repo-root D --sm SM --cuda-tag TAG
#   local dev   : bash _bundle_build.sh --repo-root D --wan-root D [--pack-only]
#
# Contracts: scripts/lib/bundle_hooks.sh. Does NOT modify flashcli-bundle.json
# (writes .build/manifest-overlay.json on finalize; pack merges it into dist/).
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

REPO_ROOT=""
WAN_ROOT=""
GIT_REF="main"
RUNTIME_VERSION="1.0.0"
SM=""
CUDA_TAG=""
OS_NAME="linux"
CPU_ARCH="x86_64"
GPU_ARCH=""
BUILD_DIR=""
JOBS="$(nproc 2>/dev/null || echo 4)"
SKIP_BUILD=0
FLASHRT_TAG=""
BUILD_ID=""
MIN_DRIVER=""
CUTLASS_REF="v4.4.2"
PYTHON_BIN=""
PYTHON_MINOR=""
MERGE_NATIVE=0
SKIP_MANIFEST=0
FINALIZE_MATRIX_MANIFEST=0

log() { printf '[wan22-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Assemble the wan22 flashcli model bundle.

Usage:
  bash _bundle_build.sh --repo-root DIR --wan-root DIR [OPTIONS]
  bash _bundle_build.sh --finalize-matrix-manifest --repo-root DIR

Required (cell/local):
  --repo-root DIR   FlashRT source (CMakeLists.txt + flash_rt/ with built *.so)
  --wan-root DIR    Wan2.2 source checkout (contains the 'wan' package)

Options:
  --python-bin PATH / --python-minor NNN / --sm SM / --cuda-tag TAG
  --build-dir DIR / --git-ref REF / -j N
  --pack-only / --merge-native / --skip-manifest
  --flashrt-tag TAG / --build-id ID / --min-driver VER / --cutlass-branch REF
  -h, --help
EOF
}

is_flashrt_repo() { [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]; }

resolve_repo_root() {
  if [[ -n "${REPO_ROOT}" ]]; then
    REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
    is_flashrt_repo "${REPO_ROOT}" || die "Invalid FlashRT repo: ${REPO_ROOT}"
    return
  fi
  local c
  for c in "$(cd "${FLASHCLI_ROOT}/.." && pwd)" "$(cd "${BUNDLE_DIR}/../.." && pwd)"; do
    is_flashrt_repo "${c}" && { REPO_ROOT="${c}"; return; }
  done
  die "Cannot find FlashRT repo; pass --repo-root"
}

sync_tree() {
  local src="$1" dst="$2"; shift 2
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    local -a a=(-a); local p; for p in "$@"; do a+=(--exclude="${p}"); done
    rsync "${a[@]}" "${src}/" "${dst}/"
  else
    local -a ta=(-C "${src}"); local p; for p in "$@"; do ta+=(--exclude="${p}"); done
    tar "${ta[@]}" -cf - . | tar -C "${dst}" -xf -
  fi
}

detect_cuda_tag() {
  if command -v nvcc >/dev/null 2>&1; then
    local v; v="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
    case "${v}" in 12.4|12.5|12.6) CUDA_TAG="124";; 12.8|12.9) CUDA_TAG="128";; 13.*) CUDA_TAG="130";; *) CUDA_TAG="${v//./}"; CUDA_TAG="${CUDA_TAG:0:3}";; esac
    return
  fi
  die "nvcc not found"
}
detect_sm() {
  local cc; cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
  [[ -n "${cc}" ]] || die "nvidia-smi returned empty compute_cap"
  SM="${cc//./}"
}
detect_platform() {
  case "$(uname -s)" in Linux) OS_NAME="linux";; Darwin) OS_NAME="macos";; *) OS_NAME="linux";; esac
  CPU_ARCH="$(uname -m)"; case "${CPU_ARCH}" in amd64|x64) CPU_ARCH="x86_64";; esac
}
recommended_torch_index() { case "${CUDA_TAG}" in 128|130) echo "cu128";; *) echo "cu124";; esac; }
cuda_toolkit_version() { case "${CUDA_TAG}" in 124) echo "12.4";; 128) echo "12.8";; 130) echo "13.0";; *) echo "${CUDA_TAG:0:1}.${CUDA_TAG:1}";; esac; }
default_min_driver() { case "${CUDA_TAG}" in 128|130) echo "550.54.14";; *) echo "525.60.13";; esac; }

ensure_cutlass() {
  local d="${REPO_ROOT}/third_party/cutlass"
  [[ -d "${d}/include" ]] && return 0
  log "Cloning CUTLASS ${CUTLASS_REF}"
  mkdir -p "${REPO_ROOT}/third_party"
  git clone --depth 1 --branch "${CUTLASS_REF}" https://github.com/NVIDIA/cutlass.git "${d}"
}

_cmake_bin() {
  command -v cmake >/dev/null 2>&1 && { printf 'cmake'; return; }
  local p="$(python3 -c 'import cmake;print(cmake.CMAKE_BIN_DIR)' 2>/dev/null)/cmake"
  [[ -x "${p}" ]] && { printf '%s' "${p}"; return; }
  die "cmake not found (apt install cmake or pip install cmake)"
}

# nvcc 13 ships a newer host compiler than some base images' libstdc++/glibc; if
# gcc-11 is present, force it so produced .so only need the host's glibc. In
# newer containers (gcc>=12) we let cmake auto-detect.
_host_compiler_args() {
  local -a a=()
  if [[ -x /usr/bin/g++-11 ]]; then
    a+=(-DCMAKE_CXX_COMPILER=/usr/bin/g++-11 -DCMAKE_C_COMPILER=/usr/bin/gcc-11
       -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-11)
  fi
  local cmakedir; cmakedir="$("${PYTHON_BIN}" -m pybind11 --cmakedir 2>/dev/null || true)"
  [[ -n "${cmakedir}" ]] && a+=(-Dpybind11_DIR="${cmakedir}")
  printf '%s\n' "${a[@]}"
}

run_cmake_build() {
  ensure_cutlass
  BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"
  local cmake="$(_cmake_bin)"
  local -a cmake_args=(-B "${BUILD_DIR}" -S "${REPO_ROOT}" -DGPU_ARCH="${GPU_ARCH}" -DPython3_EXECUTABLE="${PYTHON_BIN}"
    -DFA2_ARCH_NATIVE_ONLY=ON)  # wan22 does not use vendored FA2; slim build
  local arg; while IFS= read -r arg; do cmake_args+=("${arg}"); done < <(_host_compiler_args)
  clean_flashrt_shared_native_outputs "${REPO_ROOT}"
  log "CMake configure GPU_ARCH=${GPU_ARCH} ($("${PYTHON_BIN}" --version 2>&1 | head -1))"
  "${cmake}" "${cmake_args[@]}"
  "${cmake}" --build "${BUILD_DIR}" -j"${JOBS}" --target flash_rt_kernels
  snapshot_flashrt_native_to_build_dir "${REPO_ROOT}" "${BUILD_DIR}"
}

# Stage minimal flash_rt/ (wan22 load path only) + wan/ package.
# flash_rt/ comes from the SAME REPO_ROOT that built the .so (version-locked);
# the commit is recorded in flash_rt/BUNDLE_VERSION.
stage_wan22_python() {
  local py_dir="${BUNDLE_DIR}/flash_rt" wan_dir="${BUNDLE_DIR}/wan"
  rm -rf "${py_dir}"; mkdir -p "${py_dir}"
  local rel
  for rel in __init__.py api.py \
             hardware/__init__.py \
             frontends/__init__.py frontends/torch/__init__.py frontends/torch/wan22_rtx.py; do
    mkdir -p "${py_dir}/$(dirname "${rel}")"
    [[ -f "${REPO_ROOT}/flash_rt/${rel}" ]] || die "FlashRT missing flash_rt/${rel}"
    cp -a "${REPO_ROOT}/flash_rt/${rel}" "${py_dir}/${rel}"
  done
  local _commit _tag
  _commit="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  _tag="$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)"
  printf 'flashrt_commit=%s\nflashrt_tag=%s\nflashrt_abi=%s\nsource_repo=%s\n' \
    "${_commit}" "${_tag}" "${FLASHRT_ABI:-dev}" "${REPO_ROOT}" > "${py_dir}/BUNDLE_VERSION"

  if [[ -n "${WAN_ROOT}" ]]; then
    rm -rf "${wan_dir}"
    sync_tree "${WAN_ROOT}/wan" "${wan_dir}" '__pycache__' '*.pyc' \
      'speech2video.py' 'animate.py' 'modules/animate' 'modules/s2v'
    # t2v/i2v subset: drop speech2video/animate eager imports so decord/librosa/
    # peft/cv2 (absent/fragile on some mirrors) are not required at import time.
    cat > "${wan_dir}/__init__.py" <<'PY'
from . import configs, distributed, modules
from .image2video import WanI2V
from .text2video import WanT2V
from .textimage2video import WanTI2V
PY
    log "Staged flash_rt/ (6 .py, commit ${_commit}) + wan/ ($(find "${wan_dir}" -name '*.py'|wc -l) py, t2v subset)"
  else
    log "Staged flash_rt/ (6 .py, commit ${_commit}) (wan/ preserved)"
  fi
}

stage_bundle_runtime() {
  local lib_dir="${BUNDLE_DIR}"
  [[ "${MERGE_NATIVE}" -eq 1 ]] && { lib_dir="${BUNDLE_DIR}/lib"; mkdir -p "${lib_dir}"; }
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}/native-out"
  [[ -d "${build_src}" ]] || build_src="${REPO_ROOT}/flash_rt"
  [[ "${MERGE_NATIVE}" -ne 1 ]] && { rm -rf "${BUNDLE_DIR}/runtime"; rm -f "${BUNDLE_DIR}"/flash_rt_*.so; }

  local git_commit flashrt_tag flashrt_abi native_tag kernels_name
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  flashrt_tag="${FLASHRT_TAG:-$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)}"
  flashrt_abi="$(sanitize_flashrt_abi "${flashrt_tag}" "${git_commit}")"
  native_tag="$(native_artifact_tag "${flashrt_abi}" "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PYTHON_MINOR}")"
  kernels_name="$(native_so_filename flash_rt_kernels "${native_tag}")"
  log "Native artifact: ${kernels_name}"

  stage_native_module_to_lib "${build_src}" "${lib_dir}" flash_rt_kernels "${kernels_name}" "${PYTHON_MINOR}"

  if [[ "${SKIP_MANIFEST}" -eq 1 ]]; then
    mkdir -p "${FLASHCLI_ROOT}/.native-cache/${native_tag}"
    cp -f "${lib_dir}/${kernels_name}" "${FLASHCLI_ROOT}/.native-cache/${native_tag}/"
    return 0
  fi

  run_manifest_overlay "${BUNDLE_DIR}" "${lib_dir}" "${GEN_MANIFEST}" "${REPO_ROOT}" "${PYTHON_BIN}" \
    --runtime-version "${RUNTIME_VERSION}" --flashrt-tag "${flashrt_tag}" --git-commit "${git_commit}" \
    --build-id "${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}" --git-ref "${GIT_REF}" --sm "${SM}" \
    --os-name "${OS_NAME}" --cpuarch "${CPU_ARCH}" --gpu-arch "${GPU_ARCH}" --cuda-tag "${CUDA_TAG}" \
    --toolkit "$(cuda_toolkit_version)" --torch-index "$(recommended_torch_index)" \
    --min-driver "${MIN_DRIVER:-$(default_min_driver)}" --has-fa2 0 --has-fp4 0 --has-fmha 0 \
    --python-minor "${PYTHON_MINOR}" --native-artifact-tag "${native_tag}" >/dev/null
  mkdir -p "${FLASHCLI_ROOT}/.native-cache/${native_tag}"
  cp -f "${lib_dir}/${kernels_name}" "${FLASHCLI_ROOT}/.native-cache/${native_tag}/"
}

finalize_matrix_manifest() {
  local native_lib="${BUNDLE_DIR}/lib"
  [[ -d "${native_lib}" ]] || die "Missing ${native_lib} for --finalize-matrix-manifest"
  log "Finalizing multi-env manifest overlay from ${native_lib}"
  run_manifest_overlay "${BUNDLE_DIR}" "${native_lib}" "${GEN_MANIFEST}" "${REPO_ROOT}" "${PYTHON_BIN:-python3}" \
    --matrix-manifest --runtime-version "${RUNTIME_VERSION}" --flashrt-tag "${FLASHRT_TAG:-dev}" \
    --git-commit "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)" \
    --build-id "${BUILD_ID:-matrix}" --git-ref "${GIT_REF}" --sm "${SM:-120}" \
    --os-name "${OS_NAME:-linux}" --cpuarch "${CPU_ARCH:-x86_64}" --gpu-arch "${GPU_ARCH:-120}" \
    --cuda-tag "${CUDA_TAG:-130}" --toolkit "13.0" --torch-index "cu128" --min-driver "550.54.14" \
    --has-fa2 0 --has-fp4 0 --has-fmha 0 --python-minor "${PYTHON_MINOR:-310}" >/dev/null
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --wan-root) WAN_ROOT="$2"; shift 2 ;;
    --git-ref) GIT_REF="$2"; shift 2 ;;
    --runtime-version) RUNTIME_VERSION="$2"; shift 2 ;;
    --gpu-arch) GPU_ARCH="$2"; shift 2 ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    -j|--jobs) JOBS="$2"; shift 2 ;;
    --pack-only|--skip-build) SKIP_BUILD=1; shift ;;
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
  resolve_repo_root; detect_platform; finalize_matrix_manifest
  log "Matrix manifest overlay ready: ${BUNDLE_DIR}/.build/manifest-overlay.json"
  exit 0
fi

resolve_repo_root
detect_platform
[[ "${OS_NAME}" != "linux" && "${SKIP_BUILD}" -eq 0 ]] && die "Full build requires Linux; use --pack-only elsewhere"

[[ -n "${SM}" ]] || detect_sm
[[ -n "${CUDA_TAG}" ]] || detect_cuda_tag
GPU_ARCH="${GPU_ARCH:-${SM}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
[[ -n "${PYTHON_MINOR}" ]] || PYTHON_MINOR="$("${PYTHON_BIN}" -c 'import sys;print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"

[[ -d "${WAN_ROOT}/wan" ]] || die "Wan2.2 source (wan/ package) not found: pass --wan-root"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  run_cmake_build
else
  log "Skipping cmake (--pack-only)"
fi
stage_wan22_python
stage_bundle_runtime
log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
log "  flashcli pull ${BUNDLE_DIR}"
log "  flashcli run ${BUNDLE_DIR}"
