#!/usr/bin/env bash
# Assemble the Pi0.5 + FlashRT-Nexus bundle.
#
#   bash build.sh --repo-root /app/FlashRT --nexus-src /app/FlashRT-Nexus
#   bash build.sh --pack-only --repo-root /app/FlashRT
#   bash matrix_cell.sh ...          # release matrix
#   bash finalize_manifest.sh ...    # after full matrix
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
NEXUS_SRC=""
OUTPUT_DIR=""
GIT_REF="main"
RUNTIME_VERSION="1.0.0"
SM=""
CUDA_TAG=""
OS_NAME=""
CPU_ARCH=""
GPU_ARCH=""
BUILD_DIR=""
CPP_BUILD_DIR=""
NEXUS_BUILD_DIR=""
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
SKIP_BUILD=0
FLASHRT_TAG=""
BUILD_ID=""
MIN_DRIVER=""
CUTLASS_REF="v4.4.2"
PYTHON_BIN=""
PYTHON_MINOR=""
NEXUS_VERSION="1.0.0"
NEXUS_REPO="https://github.com/LiangSu8899/FlashRT-Nexus.git"
NEXUS_REF=""
MERGE_NATIVE=0
SKIP_MANIFEST=0
FINALIZE_MATRIX_MANIFEST=0

usage() {
  cat <<EOF
Assemble the Pi0.5 + FlashRT-Nexus flashcli bundle.

Usage:
  bash bundles/pi05_libero_nexus/build.sh [OPTIONS]

Required:
  --repo-root DIR         FlashRT source (must contain CMakeLists.txt + flash_rt/)
  --nexus-src DIR         FlashRT-Nexus source (cloned from ${NEXUS_REPO})
                          If omitted, clone --nexus-ref (default: main) into
                          \${repo_root}/../FlashRT-Nexus.

Options:
  --output-dir DIR        Also write tarball here (optional)
  --git-ref REF           Record git_ref in manifest overlay (default: main)
  --runtime-version VER   manifest runtime_version (default: 1.0.0)
  --nexus-version VER     Nexus semantic version recorded in VERSION (default: 1.0.0)
  --nexus-ref REF         Git ref to clone Nexus at (default: main)
  --gpu-arch ARCH         CMake -DGPU_ARCH= (default: auto SM)
  --build-dir DIR         FlashRT root build dir (default: <repo>/build)
  --cpp-build-dir DIR     FlashRT cpp/ build dir (default: <bundle>/.build/cpp)
  --nexus-build-dir DIR   Nexus build dir (default: <bundle>/.build/nexus)
  -j, --jobs N            Parallel cmake jobs
  --pack-only             Skip cmake; stage existing .so (developer shortcut)
  --python-bin BIN        Python for manifest ABI tag (default: python3)
  --python-minor TAG      310 / 311 / 312 (default: from --python-bin)
  --sm SM                 SM label (default: auto from GPU; release matrix uses 120)
  --cuda-tag TAG          CUDA tag 124 / 130 (default: from nvcc)
  --merge-native          Keep existing flash_rt/ when staging
  --skip-manifest         Skip .build/manifest-overlay.json
  --finalize-matrix-manifest  After full matrix, scan lib/ and write multi-env manifest
  -h, --help

Note: Requires SM120 + CUDA 13.0. Release: bash release.sh.
EOF
}

log() { printf '[pi05-nexus-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

copy_dir() {
  local src="$1" dst="$2"
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${src}/" "${dst}/"
  else
    cp -a "${src}/." "${dst}/"
  fi
}

sync_tree() {
  local src="$1" dst="$2"; shift 2
  local excludes=("$@")
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    local -a args=(-a)
    local pat
    for pat in "${excludes[@]}"; do args+=(--exclude="${pat}"); done
    rsync "${args[@]}" "${src}/" "${dst}/"
    return 0
  fi
  local -a tar_args=(-C "${src}")
  for pat in "${excludes[@]}"; do tar_args+=(--exclude="${pat}"); done
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
    "$(cd "${BUNDLE_DIR}/../.." && pwd)" \
    "$(cd "${BUNDLE_DIR}/../../.." && pwd)"; do
    if is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      return
    fi
  done
  die "Cannot find FlashRT repo; pass --repo-root"
}

resolve_nexus_src() {
  if [[ -n "${NEXUS_SRC}" ]]; then
    NEXUS_SRC="$(cd "${NEXUS_SRC}" && pwd)"
    [[ -d "${NEXUS_SRC}/core" && -f "${NEXUS_SRC}/CMakeLists.txt" ]] \
      || die "Invalid Nexus src: ${NEXUS_SRC} (need CMakeLists.txt + core/)"
    return
  fi
  local default="${REPO_ROOT}/../FlashRT-Nexus"
  if [[ -d "${default}/core" && -f "${default}/CMakeLists.txt" ]]; then
    NEXUS_SRC="$(cd "${default}" && pwd)"
    log "Auto-detected Nexus src: ${NEXUS_SRC}"
    return
  fi
  if [[ -z "${NEXUS_REF}" ]]; then NEXUS_REF="main"; fi
  NEXUS_SRC="${REPO_ROOT}/../FlashRT-Nexus"
  log "Cloning Nexus ${NEXUS_REF} → ${NEXUS_SRC}"
  git clone --depth 1 --branch "${NEXUS_REF}" "${NEXUS_REPO}" "${NEXUS_SRC}"
}

ensure_runtime_requirements_file() {
  local dest="${REPO_ROOT}/requirements/runtime-inference.txt"
  [[ -f "${dest}" ]] && return 0
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
      12.8|12.9)      CUDA_TAG="128" ;;
      13.*)           CUDA_TAG="130" ;;
      *)              CUDA_TAG="${ver//./}"; CUDA_TAG="${CUDA_TAG:0:3}" ;;
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
    Linux)            OS_NAME="linux" ;;
    Darwin)           OS_NAME="macos" ;;
    MINGW*|MSYS*|CYGWIN*) OS_NAME="win" ;;
    *)                OS_NAME="linux" ;;
  esac
  CPU_ARCH="$(uname -m)"
  case "${CPU_ARCH}" in amd64|x64) CPU_ARCH="x86_64";; esac
}

recommended_torch_index() {
  case "${CUDA_TAG}" in 128|130) echo "cu128";; *) echo "cu124";; esac
}
cuda_toolkit_version() {
  case "${CUDA_TAG}" in 124) echo "12.4";; 128) echo "12.8";; 130) echo "13.0";;
                          *) echo "${CUDA_TAG:0:1}.${CUDA_TAG:1}";; esac
}
default_min_driver() {
  case "${CUDA_TAG}" in 128|130) echo "550.54.14";; *) echo "525.60.13";; esac
}

ensure_cutlass() {
  local cutlass_dir="${REPO_ROOT}/third_party/cutlass"
  [[ -d "${cutlass_dir}/include" ]] && return 0
  log "Cloning CUTLASS ${CUTLASS_REF}"
  mkdir -p "${REPO_ROOT}/third_party"
  git clone --depth 1 --branch "${CUTLASS_REF}" \
    https://github.com/NVIDIA/cutlass.git "${cutlass_dir}"
}

# -----------------------------------------------------------------------------
# Build steps
# -----------------------------------------------------------------------------

run_flashrt_root_build() {
  # Build pybind extensions (flash_rt_kernels + flash_rt_fa2) via FlashRT root.
  ensure_cutlass
  BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build}"
  local py_bin="${PYTHON_BIN:-python3}"
  local -a cmake_args=(
    -B "${BUILD_DIR}"
    -S "${REPO_ROOT}"
    -DGPU_ARCH="${GPU_ARCH}"
    -DPython3_EXECUTABLE="${py_bin}"
  )
  clean_flashrt_shared_native_outputs "${REPO_ROOT}"
  log "FlashRT root cmake (pybind ext): GPU_ARCH=${GPU_ARCH} py=${py_bin}"
  cmake "${cmake_args[@]}"
  cmake --build "${BUILD_DIR}" -j"${JOBS}" --target flash_rt_kernels flash_rt_fa2
  snapshot_flashrt_native_to_build_dir "${REPO_ROOT}" "${BUILD_DIR}"
}

run_flashrt_cpp_build() {
  # Standalone cpp/ build → libflashrt_exec + libflashrt_runtime + libflashrt_cpp_pi05_c
  CPP_BUILD_DIR="${CPP_BUILD_DIR:-${BUNDLE_DIR}/.build/cpp}"
  local py_bin="${PYTHON_BIN:-python3}"
  log "FlashRT cpp/ standalone cmake at ${CPP_BUILD_DIR}"
  cmake -S "${REPO_ROOT}/cpp" -B "${CPP_BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DFLASHRT_CPP_WITH_EXEC=ON \
    -DFLASHRT_CPP_WITH_CUDA_STAGING=ON \
    -DFLASHRT_CPP_WITH_CUDA_KERNELS=ON
  cmake --build "${CPP_BUILD_DIR}" -j"${JOBS}" --target \
    flashrt_exec flashrt_cpp_pi05_c
}

run_nexus_build() {
  NEXUS_BUILD_DIR="${NEXUS_BUILD_DIR:-${BUNDLE_DIR}/.build/nexus}"
  local exec_so="${CPP_BUILD_DIR}/exec/libflashrt_exec.so"
  [[ -f "${exec_so}" ]] || die "libflashrt_exec.so missing at ${exec_so}"
  log "Nexus cmake at ${NEXUS_BUILD_DIR} (links ${exec_so})"
  cmake -S "${NEXUS_SRC}" -B "${NEXUS_BUILD_DIR}" \
    -DCAPSULE_BUILD_FLASHRT_BACKEND=ON \
    -DFLASHRT_EXEC_DIR="${REPO_ROOT}/exec" \
    -DFLASHRT_EXEC_LIB="${exec_so}" \
    -DFLASHRT_RUNTIME_DIR="${REPO_ROOT}/runtime" \
    -DCMAKE_BUILD_TYPE=Release
  cmake --build "${NEXUS_BUILD_DIR}" -j"${JOBS}" --target capsule_nexus_flashrt
}

# -----------------------------------------------------------------------------
# Staging
# -----------------------------------------------------------------------------

stage_pi05_flash_rt_minimal() {
  local dst="$1"
  local src="${REPO_ROOT}/flash_rt"
  if [[ "${MERGE_NATIVE}" -eq 1 && -d "${dst}" ]]; then
    log "Keeping existing flash_rt/ (--merge-native)"
    return 0
  fi
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

  mkdir -p "${dst}/models/pi05"
  sync_tree "${src}/models/pi05" "${dst}/models/pi05" 'pipeline_thor*' '__pycache__'

  for rel in \
    frontends/__init__.py \
    frontends/_fp8_layout.py \
    frontends/torch/__init__.py \
    frontends/torch/pi05_rtx.py \
    frontends/torch/pi05_rtx_fp16.py \
    frontends/torch/pi05_rtx_batched.py \
    frontends/torch/pi05_rtx_cfg.py \
    frontends/torch/pi05_rtx_cfg_batched.py; do
    [[ -f "${src}/${rel}" ]] && _cp_file "${rel}"
  done

  _cp_file hardware/__init__.py
  [[ -f "${src}/hardware/backend.py" ]] && _cp_file hardware/backend.py

  mkdir -p "${dst}/hardware/rtx"
  for rel in attn_backend.py attn_backend_batched_pi05.py; do
    [[ -f "${src}/hardware/rtx/${rel}" ]] && \
      cp -a "${src}/hardware/rtx/${rel}" "${dst}/hardware/rtx/${rel}"
  done

  mkdir -p "${dst}/core"
  sync_tree "${src}/core" "${dst}/core" '*.so' '__pycache__'

  mkdir -p "${dst}/executors"
  for rel in __init__.py torch_weights.py weight_loader.py; do
    [[ -f "${src}/executors/${rel}" ]] && cp -a "${src}/executors/${rel}" "${dst}/executors/${rel}"
  done

  mkdir -p "${dst}/utils"
  sync_tree "${src}/utils" "${dst}/utils" '__pycache__'

  # Nexus producer needs runtime/ (export.py) + subgraphs/ (stage_plan)
  mkdir -p "${dst}/runtime"
  sync_tree "${src}/runtime" "${dst}/runtime" '__pycache__'
  mkdir -p "${dst}/subgraphs"
  sync_tree "${src}/subgraphs" "${dst}/subgraphs" '__pycache__'

  log "Staged flash_rt/ ($(find "${dst}" -type f -name '*.py' | wc -l) py files)"
}

stage_nexus_python() {
  local dst="$1"   # <env_key>/substrate/nexus_python/
  local src="${NEXUS_SRC}/serve"
  rm -rf "${dst}"
  mkdir -p "${dst}/producer_plugins" "${dst}/transports"
  for f in __init__.py embedded.py deployment.py session.py ffi.py manifest.py producers.py; do
    [[ -f "${src}/${f}" ]] && cp -a "${src}/${f}" "${dst}/${f}"
  done
  [[ -f "${src}/producer_plugins/__init__.py" ]] && \
    cp -a "${src}/producer_plugins/__init__.py" "${dst}/producer_plugins/__init__.py"
  [[ -f "${src}/producer_plugins/pi05.py" ]] && \
    cp -a "${src}/producer_plugins/pi05.py" "${dst}/producer_plugins/pi05.py"
  if [[ -d "${src}/transports" ]]; then
    rsync -a --exclude='__pycache__' "${src}/transports/" "${dst}/transports/" \
      2>/dev/null || copy_dir "${src}/transports" "${dst}/transports"
  fi
  # Rewrite imports: serve.* → nexus_python.*
  find "${dst}" -name '*.py' -exec sed -i \
    -e 's/from serve\./from nexus_python./g' \
    -e 's/import serve\./import nexus_python./g' \
    -e 's/"serve\./"nexus_python./g' \
    -e 's|serve\.producer_plugins|nexus_python.producer_plugins|g' {} +
  log "Staged nexus_python/ ($(find "${dst}" -type f -name '*.py' | wc -l) py files)"
}

write_version_file() {
  local dst="$1"   # <env_key>/substrate/VERSION
  local fr_full fr_short nx_full nx_short
  fr_full="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  fr_short="$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  nx_full="$(git -C "${NEXUS_SRC}" rev-parse HEAD 2>/dev/null || echo unknown)"
  nx_short="$(git -C "${NEXUS_SRC}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  cat > "${dst}" <<EOF
{
  "flashrt_sha":   "${fr_full}",
  "flashrt_short": "${fr_short}",
  "nexus_sha":     "${nx_full}",
  "nexus_short":   "${nx_short}",
  "nexus_version": "${NEXUS_VERSION}",
  "cuda":          "$(cuda_toolkit_version)",
  "sm":            "${SM}",
  "python_abi":    "${PYTHON_MINOR}",
  "platform_key":  "sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}",
  "env_key":       "sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}-py${PYTHON_MINOR}",
  "composite_tag": "fr${fr_short}.nx${nx_short}",
  "build_id":      "${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}",
  "built_at":      "$(date -u +%FT%TZ)"
}
EOF
  log "Wrote ${dst} (fr=${fr_short} nx=${nx_short})"
}

stage_bundle_runtime() {
  local py_bin="${PYTHON_BIN:-python3}"
  if [[ -z "${PYTHON_MINOR}" ]]; then
    PYTHON_MINOR="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")')"
  fi

  local env_key="sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}-py${PYTHON_MINOR}"
  local platform_key="sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"
  local rt_dir="${BUNDLE_DIR}/runtime/${env_key}"
  local sub_dir="${rt_dir}/substrate"
  local build_src="${BUILD_DIR:-${REPO_ROOT}/build}/native-out"

  rm -rf "${rt_dir}"
  mkdir -p "${sub_dir}"

  local fr_short nx_short
  fr_short="$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  nx_short="$(git -C "${NEXUS_SRC}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  local composite="fr${fr_short}.nx${nx_short}"
  local py_tag="${fr_short}-${env_key}"
  local c_tag="${fr_short}-${platform_key}"
  local nexus_tag="${composite}-${platform_key}"

  # 1) Python extensions to runtime/<env>/ (top level — flashcli loader finds them)
  if [[ ! -d "${build_src}" ]] || ! compgen -G "${build_src}"/*.so >/dev/null; then
    build_src="${REPO_ROOT}/flash_rt"
  fi
  stage_native_module_to_lib "${build_src}" "${rt_dir}" flash_rt_kernels \
    "$(native_so_filename flash_rt_kernels "${py_tag}")" "${PYTHON_MINOR}" \
    || die "flash_rt_kernels missing (rebuild FlashRT or --pack-only with existing .so)"
  stage_native_module_to_lib "${build_src}" "${rt_dir}" flash_rt_fa2 \
    "$(native_so_filename flash_rt_fa2 "${py_tag}")" "${PYTHON_MINOR}" \
    || die "flash_rt_fa2 missing"
  log "Staged py extensions: flash_rt_kernels flash_rt_fa2 (-py${PYTHON_MINOR})"

  # 2) C libraries to runtime/<env>/substrate/ (subdir — validator skips)
  local exec_src="${CPP_BUILD_DIR}/exec/libflashrt_exec.so"
  local prod_src="${CPP_BUILD_DIR}/libflashrt_cpp_pi05_c.so"
  local nex_src="${NEXUS_BUILD_DIR}/libcapsule_nexus_flashrt.so"
  [[ -f "${exec_src}" ]] || die "missing ${exec_src} (run cpp build)"
  [[ -f "${prod_src}" ]] || die "missing ${prod_src}"
  [[ -f "${nex_src}"  ]] || die "missing ${nex_src} (run Nexus build)"
  cp -f "${exec_src}" "${sub_dir}/libflashrt_exec-${c_tag}.so"
  cp -f "${prod_src}" "${sub_dir}/libflashrt_cpp_pi05_c-${c_tag}.so"
  cp -f "${nex_src}"  "${sub_dir}/libcapsule_nexus_flashrt-${nexus_tag}.so"
  log "Staged C libs: libflashrt_exec libflashrt_cpp_pi05_c libcapsule_nexus_flashrt"

  # 2b) _flashrt_exec + _flashrt_runtime pybind dev modules.
  #     flash_rt/runtime/exec.py imports _flashrt_exec, flash_rt/runtime/export.py
  #     imports _flashrt_runtime. The Nexus producer plugin transitively loads
  #     these. Lives in substrate/ (loader puts substrate/ on sys.path).
  #     Python-native filenames so import finds them.
  local exec_pybind_src="${CPP_BUILD_DIR}/exec/_flashrt_exec.cpython-310-x86_64-linux-gnu.so"
  local runtime_pybind_src="${CPP_BUILD_DIR}/runtime/_flashrt_runtime.cpython-310-x86_64-linux-gnu.so"
  if [[ ! -f "${exec_pybind_src}" || ! -f "${runtime_pybind_src}" ]]; then
    log "Building _flashrt_exec + _flashrt_runtime pybind modules (standalone)"
    local exec_bld="${BUNDLE_DIR}/.build/exec-pybind"
    local runtime_bld="${BUNDLE_DIR}/.build/runtime-pybind"
    cmake -S "${REPO_ROOT}/exec" -B "${exec_bld}" -DCMAKE_BUILD_TYPE=Release
    cmake --build "${exec_bld}" -j"${JOBS}" --target _flashrt_exec
    cmake -S "${REPO_ROOT}/runtime" -B "${runtime_bld}" -DCMAKE_BUILD_TYPE=Release
    cmake --build "${runtime_bld}" -j"${JOBS}" --target _flashrt_runtime
    exec_pybind_src="${exec_bld}/_flashrt_exec.cpython-310-x86_64-linux-gnu.so"
    runtime_pybind_src="${runtime_bld}/_flashrt_runtime.cpython-310-x86_64-linux-gnu.so"
  fi
  [[ -f "${exec_pybind_src}" ]] || die "missing _flashrt_exec pybind module"
  [[ -f "${runtime_pybind_src}" ]] || die "missing _flashrt_runtime pybind module"
  cp -f "${exec_pybind_src}"    "${sub_dir}/_flashrt_exec.cpython-310-x86_64-linux-gnu.so"
  cp -f "${runtime_pybind_src}" "${sub_dir}/_flashrt_runtime.cpython-310-x86_64-linux-gnu.so"
  log "Staged _flashrt_exec + _flashrt_runtime pybind modules"

  # 3) Nexus Python package (vendored, import paths rewritten)
  stage_nexus_python "${sub_dir}/nexus_python"

  # 4) VERSION — single source of truth for the ABI fingerprint
  write_version_file "${sub_dir}/VERSION"

  # 5) slim flash_rt/ at bundle root
  if [[ "${MERGE_NATIVE}" -ne 1 ]] || [[ ! -d "${BUNDLE_DIR}/flash_rt" ]]; then
    stage_pi05_flash_rt_minimal "${BUNDLE_DIR}/flash_rt"
  fi
  find "${BUNDLE_DIR}/flash_rt" -name '*.so' -type f -delete 2>/dev/null || true

  # 6) ldd cross-check: nexus MUST link exec
  if command -v ldd >/dev/null 2>&1; then
    if ! ldd "${sub_dir}/libcapsule_nexus_flashrt-${nexus_tag}.so" \
            | grep -q 'libflashrt_exec'; then
      die "libcapsule_nexus_flashrt does not link libflashrt_exec — build is broken"
    fi
    log "ldd OK: nexus links bundled libflashrt_exec"
  fi
}

write_manifest_overlay() {
  local py_bin="${PYTHON_BIN:-python3}"
  local build_id="${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}"
  local torch_idx
  torch_idx="$(recommended_torch_index)"
  local min_drv="${MIN_DRIVER:-$(default_min_driver)}"
  local flashrt_tag="${FLASHRT_TAG:-$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)}"
  local git_commit
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  local nexus_short
  nexus_short="$(git -C "${NEXUS_SRC}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  local composite="fr${flashrt_tag}.nx${nexus_short}"

  run_manifest_overlay "${BUNDLE_DIR}" "" "${GEN_MANIFEST}" "${REPO_ROOT}" "${py_bin}" \
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
    --has-fa2 1 \
    --has-fp4 0 \
    --has-fmha 0 \
    --python-minor "${PYTHON_MINOR}" \
    --native-artifact-tag "${flashrt_tag}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}-py${PYTHON_MINOR}"

  # Augment overlay with Nexus fields (idempotent Python edit)
  "${py_bin}" - <<PY
import json, pathlib
p = pathlib.Path("${BUNDLE_DIR}/.build/manifest-overlay.json")
d = json.loads(p.read_text())
d.setdefault("build", {}).update({
    "nexus_repo":   "${NEXUS_REPO}",
    "nexus_ref":    "${NEXUS_REF:-main}",
    "nexus_sha":    "$(git -C "${NEXUS_SRC}" rev-parse HEAD 2>/dev/null || echo unknown)",
    "nexus_short":  "${nexus_short}",
    "nexus_version":"${NEXUS_VERSION}",
    "nexus_tag":    "${composite}",
})
d["build"].setdefault("features", {})["nexus"] = True
p.write_text(json.dumps(d, indent=2))
print(f"[pi05-nexus-bundle] overlay: {p}")
PY
}

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)         REPO_ROOT="$2"; shift 2 ;;
    --nexus-src)         NEXUS_SRC="$2"; shift 2 ;;
    --nexus-ref)         NEXUS_REF="$2"; shift 2 ;;
    --nexus-version)     NEXUS_VERSION="$2"; shift 2 ;;
    --output-dir)        OUTPUT_DIR="$2"; shift 2 ;;
    --git-ref)           GIT_REF="$2"; shift 2 ;;
    --runtime-version)   RUNTIME_VERSION="$2"; shift 2 ;;
    --gpu-arch)          GPU_ARCH="$2"; shift 2 ;;
    --build-dir)         BUILD_DIR="$2"; shift 2 ;;
    --cpp-build-dir)     CPP_BUILD_DIR="$2"; shift 2 ;;
    --nexus-build-dir)   NEXUS_BUILD_DIR="$2"; shift 2 ;;
    -j|--jobs)           JOBS="$2"; shift 2 ;;
    --pack-only|--skip-build) SKIP_BUILD=1; shift ;;
    --python-bin)        PYTHON_BIN="$2"; shift 2 ;;
    --python-minor)      PYTHON_MINOR="$2"; shift 2 ;;
    --sm)                SM="$2"; shift 2 ;;
    --cuda-tag)          CUDA_TAG="$2"; shift 2 ;;
    --flashrt-tag)       FLASHRT_TAG="$2"; shift 2 ;;
    --build-id)          BUILD_ID="$2"; shift 2 ;;
    --min-driver)        MIN_DRIVER="$2"; shift 2 ;;
    --cutlass-branch)    CUTLASS_REF="$2"; shift 2 ;;
    --merge-native)      MERGE_NATIVE=1; shift ;;
    --skip-manifest)     SKIP_MANIFEST=1; shift ;;
    --finalize-matrix-manifest) FINALIZE_MATRIX_MANIFEST=1; shift ;;
    -h|--help)           usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"

PYTHON_BIN="${PYTHON_BIN:-python3}"
resolve_repo_root
resolve_nexus_src
ensure_runtime_requirements_file
detect_platform

if [[ "${FINALIZE_MATRIX_MANIFEST}" -eq 1 ]]; then
  SM="${SM:-120}"; CUDA_TAG="${CUDA_TAG:-130}"; PYTHON_MINOR="${PYTHON_MINOR:-310}"
  write_manifest_overlay
  log "Matrix overlay ready."
  exit 0
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  [[ -n "${SM}" ]] || detect_sm
  [[ -n "${CUDA_TAG}" ]] || detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  command -v cmake >/dev/null 2>&1 || die "cmake not found"
  if [[ "${SM}" != "120" && "${SM}" != "121" ]]; then
    log "WARNING: Nexus backend currently tested on SM120; detected sm=${SM}"
  fi
  run_flashrt_root_build
  run_flashrt_cpp_build
  run_nexus_build
else
  [[ -z "${SM}" ]] && detect_sm
  [[ -z "${CUDA_TAG}" ]] && detect_cuda_tag
  GPU_ARCH="${GPU_ARCH:-${SM}}"
  CPP_BUILD_DIR="${CPP_BUILD_DIR:-${BUNDLE_DIR}/.build/cpp}"
  NEXUS_BUILD_DIR="${NEXUS_BUILD_DIR:-${BUNDLE_DIR}/.build/nexus}"
  log "Skipping cmake (--pack-only); using existing .so from ${CPP_BUILD_DIR} + ${NEXUS_BUILD_DIR}"
fi

stage_bundle_runtime

if [[ "${SKIP_MANIFEST}" -eq 0 ]]; then
  write_manifest_overlay
fi

log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
log "  flashcli run   ${BUNDLE_DIR} --prompt 'pick up the red block'"
log "  flashcli serve ${BUNDLE_DIR} --port 8080"
log "  Release: cd bundles/pi05_libero_nexus && bash release.sh"
