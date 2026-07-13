#!/usr/bin/env bash
# Local dev build for the wan22 bundle (single environment).
#
# Stages:
#   1. flash_rt/  — FlashRT Python tree (no .so) from a FlashRT source checkout
#   2. wan/       — official Wan2.2 Python package (vendored third-party source)
#   3. runtime/<env-key>/ — tagged native .so for this host's (SM, CUDA, py)
#
# Usage:
#   bash build.sh --repo-root /app/FlashRT --wan-root /app/Wan2.2
#   bash build.sh --repo-root /app/FlashRT --wan-root /app/Wan2.2 --env-key sm120-cu130-linux-x86_64-py310
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=""
WAN_ROOT=""
ENV_KEY=""
FLASHRT_ABI=""
PYTHON_MINOR="310"

usage() {
  cat <<EOF
Assemble the wan22 flashcli model bundle.

Usage:
  bash build.sh --repo-root DIR --wan-root DIR [OPTIONS]

Required:
  --repo-root DIR   FlashRT source (CMakeLists.txt + flash_rt/ with built *.so)
  --wan-root DIR    Wan2.2 source checkout (contains the 'wan' python package)

Options:
  --env-key KEY     runtime cell name (default: auto from nvidia-smi + nvcc)
  --flashrt-abi TAG FlashRT abi tag in .so filenames (default: FlashRT git short sha)
  --python-minor NNN  310/311/312 (default: 310)
  -h, --help
EOF
}

log() { printf '[wan22-bundle] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

is_flashrt_repo() { [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]; }

detect_env_key() {
  local cc sm cuda_major cuda_minor cuda_tag
  cc="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
  cc="${cc//./}"
  sm="${cc}"
  if command -v nvcc >/dev/null 2>&1; then
    cuda_major="$(nvcc --version | sed -n 's/.*release \([0-9]*\)\.\([0-9]*\).*/\1/p' | head -1)"
  else
    cuda_major="$(nvidia-smi | sed -n 's/.*CUDA Version: \([0-9]*\)\.\([0-9]*\).*/\1/p' | head -1)"
  fi
  [[ "${cuda_major}" -ge 13 ]] && cuda_tag="130" || cuda_tag="128"
  ENV_KEY="sm${sm}-cu${cuda_tag}-linux-x86_64-py${PYTHON_MINOR}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --wan-root) WAN_ROOT="$2"; shift 2 ;;
    --env-key) ENV_KEY="$2"; shift 2 ;;
    --flashrt-abi) FLASHRT_ABI="$2"; shift 2 ;;
    --python-minor) PYTHON_MINOR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${REPO_ROOT}" ]] || { usage; exit 1; }
[[ -n "${WAN_ROOT}" ]] || { usage; exit 1; }
REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
WAN_ROOT="$(cd "${WAN_ROOT}" && pwd)"
is_flashrt_repo "${REPO_ROOT}" || die "Invalid FlashRT repo: ${REPO_ROOT}"
[[ -d "${WAN_ROOT}/wan" ]] || die "Invalid Wan2.2 source (no wan/ package): ${WAN_ROOT}"
[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"

[[ -n "${ENV_KEY}" ]] || detect_env_key
log "env key: ${ENV_KEY}"

if [[ -z "${FLASHRT_ABI}" ]]; then
  FLASHRT_ABI="$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)"
fi
log "flashrt abi: ${FLASHRT_ABI}"

# ── 1. flash_rt/ Python tree (minimal: only the wan22 load path) ────────────
# Staged from the SAME FlashRT checkout that built the .so (REPO_ROOT), so the
# Python API and the compiled runtime are version-locked by construction. The
# FlashRT commit is recorded in flash_rt/BUNDLE_VERSION for auditing.
PY_DST="${BUNDLE_DIR}/flash_rt"
log "staging minimal flash_rt/ (wan22 load path only) -> ${PY_DST}"
rm -rf "${PY_DST}"; mkdir -p "${PY_DST}"
for rel in __init__.py api.py \
           hardware/__init__.py \
           frontends/__init__.py frontends/torch/__init__.py frontends/torch/wan22_rtx.py; do
  mkdir -p "${PY_DST}/$(dirname "${rel}")"
  [[ -f "${REPO_ROOT}/flash_rt/${rel}" ]] || die "FlashRT missing flash_rt/${rel}"
  cp -a "${REPO_ROOT}/flash_rt/${rel}" "${PY_DST}/${rel}"
done
_commit="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
_tag="$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)"
printf 'flashrt_commit=%s\nflashrt_tag=%s\nflashrt_abi=%s\nsource_repo=%s\n' \
  "${_commit}" "${_tag}" "${FLASHRT_ABI}" "${REPO_ROOT}" > "${PY_DST}/BUNDLE_VERSION"
log "flash_rt/ staged ($(find "${PY_DST}" -name '*.py' | wc -l) .py files; commit ${_commit})"

# ── 2. wan/ official package ────────────────────────────────────────────────
WAN_DST="${BUNDLE_DIR}/wan"
log "staging wan/ package (t2v subset) -> ${WAN_DST}"
rm -rf "${WAN_DST}"
mkdir -p "${WAN_DST}"
# Exclude the speech-to-video / animate implementations (decord/librosa/peft/cv2
# carriers) the t2v path never imports. Config dicts for them stay (harmless).
_WAN_EXCLUDES=(__pycache__ '*.pyc' speech2video.py animate.py modules/animate modules/s2v)
if command -v rsync >/dev/null 2>&1; then
  _args=(-a); for p in "${_WAN_EXCLUDES[@]}"; do _args+=(--exclude="${p}"); done
  rsync "${_args[@]}" "${WAN_ROOT}/wan/" "${WAN_DST}/"
else
  _ta=(-C "${WAN_ROOT}/wan"); for p in "${_WAN_EXCLUDES[@]}"; do _ta+=(--exclude="${p}"); done
  tar "${_ta[@]}" -cf - . | tar -C "${WAN_DST}" -xf -
fi
log "wan/ staged ($(find "${WAN_DST}" -name '*.py' | wc -l) .py files)"

# Trim wan/__init__.py: the t2v/i2v path never uses speech2video (WanS2V) or
# animate (WanAnimate), whose eager imports drag in decord/librosa/peft/cv2 —
# packages that are absent or fragile on some pip mirrors. Keeping the import
# surface minimal makes `flashcli pull` one-click on any standard PyPI mirror.
cat > "${WAN_DST}/__init__.py" <<'PY'
# Wan2.2 bundle — text/image-to-video subset only.
# WanS2V (speech2video) and WanAnimate (animate) are intentionally NOT imported:
# they require decord/librosa/peft/cv2, which the t2v/i2v path never exercises.
# Restore those lines only if speech-to-video or animate generation is needed.
from . import configs, distributed, modules
from .image2video import WanI2V
from .text2video import WanT2V
from .textimage2video import WanTI2V
PY
log "trimmed wan/__init__.py (t2v/i2v subset; decord/librosa/peft no longer required)"

# ── 3. runtime/<env-key>/ tagged native .so ─────────────────────────────────
CELL="${BUNDLE_DIR}/runtime/${ENV_KEY}"
log "staging native .so -> ${CELL}"
rm -rf "${BUNDLE_DIR}/runtime"
mkdir -p "${CELL}"

stage_so() {
  local module_base="$1"
  local src=""
  local f
  for f in \
    "${REPO_ROOT}/flash_rt/${module_base}.cpython-${PYTHON_MINOR}-x86_64-linux-gnu.so" \
    "${REPO_ROOT}/flash_rt/${module_base}.so" \
    "${REPO_ROOT}/build/native-out/${module_base}.cpython-${PYTHON_MINOR}-x86_64-linux-gnu.so" \
    "${REPO_ROOT}/build/native-out/${module_base}.so"; do
    [[ -f "${f}" ]] && { src="${f}"; break; }
  done
  [[ -n "${src}" ]] || die "${module_base}.so not found under ${REPO_ROOT}/flash_rt (build FlashRT first)"
  cp -f "${src}" "${CELL}/${module_base}-${FLASHRT_ABI}-${ENV_KEY}.so"
  log "  $(basename "${src}") -> ${module_base}-${FLASHRT_ABI}-${ENV_KEY}.so"
}

# Wan2.2's official pipeline routes attention through its own SDPA path (rebound
# at runtime in run.py, _apply_wan_sdpa_fallback); it never calls FlashRT's
# vendored FA2. Ship kernels only.
stage_so flash_rt_kernels

log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
log "  flashcli pull ${BUNDLE_DIR}"
log "  flashcli run ${BUNDLE_DIR}"
