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
  # Native-only: build the Python-free FA2 C library, a prerequisite for the
  # SM120 PI0.5 native frontend (FLASHRT_CPP_FA2_LIBRARY). No pybind extensions.
  ensure_cutlass
  BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build-fa2raw}"
  local py_bin="${PYTHON_BIN:-python3}"
  log "FlashRT root cmake (native fa2_raw): GPU_ARCH=${GPU_ARCH} py=${py_bin}"
  cmake -S "${REPO_ROOT}" -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DGPU_ARCH="${GPU_ARCH}" \
    -DFLASHRT_ENABLE_NATIVE_CPP=ON \
    -DPython3_EXECUTABLE="${py_bin}"
  cmake --build "${BUILD_DIR}" -j"${JOBS}" --target flashrt_fa2_raw
}

run_flashrt_cpp_build() {
  # Standalone cpp/ build → libflashrt_exec + libflashrt_cpp_pi05_c (native_v2).
  CPP_BUILD_DIR="${CPP_BUILD_DIR:-${BUNDLE_DIR}/.build/cpp}"
  local fa2="${REPO_ROOT}/flash_rt/libflashrt_fa2_raw.so"
  [[ -f "${fa2}" ]] || die "libflashrt_fa2_raw.so missing at ${fa2} (run the FA2 native build first)"
  local -a args=(
    -S "${REPO_ROOT}/cpp" -B "${CPP_BUILD_DIR}"
    -DCMAKE_BUILD_TYPE=Release
    -DFLASHRT_ENABLE_NATIVE_CPP=ON
    -DFLASHRT_CPP_WITH_EXEC=ON
    -DFLASHRT_CPP_WITH_CUDA_STAGING=ON
    -DFLASHRT_CPP_WITH_CUDA_KERNELS=ON
    -DFLASHRT_CPP_WITH_PI05=ON
    -DFLASHRT_CPP_WITH_SENTENCEPIECE=ON
    -DFLASHRT_CPP_FA2_LIBRARY="${fa2}"
  )
  case "${SM}" in
    120) args+=(-DFLASHRT_CPP_WITH_PI05_SM120_TARGET=ON) ;;
    110) args+=(-DFLASHRT_CPP_WITH_PI05_SM110_TARGET=ON) ;;
    *)   die "Unsupported SM=${SM} for the PI0.5 native target (need 120/110)" ;;
  esac
  log "FlashRT cpp/ standalone cmake at ${CPP_BUILD_DIR} (ptx sm${SM}, fa2=${fa2})"
  cmake "${args[@]}"
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
  "platform_key":  "sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}",
  "env_key":       "sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}",
  "composite_tag": "fr${fr_short}.nx${nx_short}",
  "build_id":      "${BUILD_ID:-$(date -u +%Y%m%d)-sm${SM}}",
  "built_at":      "$(date -u +%FT%TZ)"
}
EOF
  log "Wrote ${dst} (fr=${fr_short} nx=${nx_short})"
}

# Native-only staging: only the C libraries under runtime/<env>/substrate/.
# No pybind extensions, no nexus_python, no flash_rt/ — inference is Python-free.
stage_bundle_runtime_native() {
  # Native-only: runtime cell key carries no "-py{NNN}" segment.
  local env_key="sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"
  local rt_dir="${BUNDLE_DIR}/runtime/${env_key}"
  local sub_dir="${rt_dir}/substrate"
  rm -rf "${rt_dir}"
  mkdir -p "${sub_dir}"

  local exec_src="${CPP_BUILD_DIR}/exec/libflashrt_exec.so"
  local prod_src="${CPP_BUILD_DIR}/libflashrt_cpp_pi05_c.so"
  local nex_src="${NEXUS_BUILD_DIR}/libcapsule_nexus_flashrt.so"
  local fa2_src="${REPO_ROOT}/flash_rt/libflashrt_fa2_raw.so"
  [[ -f "${exec_src}" ]] || die "missing ${exec_src} (run cpp build)"
  [[ -f "${prod_src}" ]] || die "missing ${prod_src}"
  [[ -f "${nex_src}"  ]] || die "missing ${nex_src} (run Nexus build)"

  local fr_short nx_short composite c_tag nexus_tag
  fr_short="$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  nx_short="$(git -C "${NEXUS_SRC}" rev-parse --short=7 HEAD 2>/dev/null || echo dev)"
  composite="fr${fr_short}.nx${nx_short}"
  c_tag="${fr_short}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"
  nexus_tag="${composite}-sm${SM}-cu${CUDA_TAG}-${OS_NAME}-${CPU_ARCH}"

  cp -f "${exec_src}" "${sub_dir}/libflashrt_exec-${c_tag}.so"
  cp -f "${prod_src}" "${sub_dir}/libflashrt_cpp_pi05_c-${c_tag}.so"
  cp -f "${nex_src}"  "${sub_dir}/libcapsule_nexus_flashrt-${nexus_tag}.so"
  local rt_src="${CPP_BUILD_DIR}/runtime/libflashrt_runtime.so"
  [[ -f "${rt_src}" ]] || die "missing ${rt_src}"
  cp -f "${rt_src}" "${sub_dir}/libflashrt_runtime-${c_tag}.so"
  [[ -f "${fa2_src}" ]] && cp -f "${fa2_src}" "${sub_dir}/libflashrt_fa2_raw-${c_tag}.so"
  log "Staged native substrate: exec + runtime + pi05_c + nexus_flashrt (+fa2_raw)"

  # Native-exec lane: bundle-owned Go server (self-contained) + ABI descriptor.
  local bin_dir="${rt_dir}/bin"
  mkdir -p "${bin_dir}"
  local srv_version
  srv_version="$(sed -n 's/^version *= *"\(.*\)"/\1/p' "${FLASHCLI_ROOT}/pyproject.toml" | head -1)"
  [[ -n "${srv_version}" ]] || srv_version="dev"
  log "Building native-exec server (bundle native_exec/) version ${srv_version}"
  ( cd "${BUNDLE_DIR}/native_exec" && CGO_ENABLED=0 go build -trimpath \
      -ldflags "-X main.version=${srv_version}" \
      -o "${bin_dir}/pi05_exec_server" . )
  cp -f "${BUNDLE_DIR}/exec_server.json" "${rt_dir}/exec_server.json"
  log "Staged native-exec server: bin/pi05_exec_server + exec_server.json"

  write_version_file "${sub_dir}/VERSION"

  if command -v ldd >/dev/null 2>&1; then
    if ldd "${sub_dir}/libcapsule_nexus_flashrt-${nexus_tag}.so" | grep -q 'libflashrt_exec'; then
      log "ldd OK: nexus links bundled libflashrt_exec"
    else
      log "note: nexus does not link libflashrt_exec (kept loadable via preload)"
    fi
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
    --python-minor "${PYTHON_MINOR:-310}" \
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
# Native-only: do not record python_abi (there is no Python entry).
if '"python_abi"' not in pathlib.Path("${BUNDLE_DIR}/flashcli-bundle.json").read_text():
    d.pop("python_abi", None)
    d.get("build", {}).get("target", {}).pop("python_abi", None)
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

stage_bundle_runtime_native

if [[ "${SKIP_MANIFEST}" -eq 0 ]]; then
  write_manifest_overlay
fi

log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
log "  flashcli run   ${BUNDLE_DIR} --prompt 'pick up the red block'"
log "  flashcli serve ${BUNDLE_DIR} --port 8080"
log "  Release: cd bundles/pi05_libero_nexus && bash release.sh"
