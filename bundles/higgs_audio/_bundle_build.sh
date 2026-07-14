#!/usr/bin/env bash
# Higgs Audio v3 bundle build & staging.
#
#   bash build.sh --repo-root /app/FlashRT
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

REPO_ROOT=""
SKIP_BUILD=0
SM=""
CUDA_TAG=""
PY_MINOR="310"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --pack-only) SKIP_BUILD=1; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "${REPO_ROOT}" ]] || { echo "ERROR: --repo-root required" >&2; exit 1; }
SRC="${REPO_ROOT}/flash_rt"

log() { printf '[higgs-bundle] %s\n' "$*" >&2; }

# ── Detect platform ────────────────────────────────────────────────
[[ -n "${SM}" ]] || SM="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' | tr -d '.')"
[[ -n "${CUDA_TAG}" ]] || CUDA_TAG="130"
OS_NAME="linux"
CPU_ARCH="x86_64"

git_commit="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
flashrt_abi="$(sanitize_flashrt_abi "${git_commit}" "${git_commit}")"
native_tag="$(native_artifact_tag "${flashrt_abi}" "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PY_MINOR}")"
env_key="$(runtime_env_key "${SM}" "${CUDA_TAG}" "${OS_NAME}" "${CPU_ARCH}" "${PY_MINOR}")"
kernels_name="$(native_so_filename flash_rt_kernels "${native_tag}")"
fa2_name="$(native_so_filename flash_rt_fa2 "${native_tag}")"

log "FlashRT commit: ${git_commit}"
log "Native tag: ${native_tag}"
log "Env key: ${env_key}"

# ── Stage runtime/ .so files ───────────────────────────────────────
stage_runtime() {
  local rt_dir="${BUNDLE_DIR}/runtime/${env_key}"
  rm -rf "${BUNDLE_DIR}/runtime"
  mkdir -p "${rt_dir}"

  stage_native_module_to_lib "${SRC}" "${rt_dir}" flash_rt_kernels "${kernels_name}" "${PY_MINOR}"
  log "Staged ${kernels_name}"

  if stage_native_module_to_lib "${SRC}" "${rt_dir}" flash_rt_fa2 "${fa2_name}" "${PY_MINOR}" 2>/dev/null; then
    log "Staged ${fa2_name}"
  else
    log "WARN: flash_rt_fa2 not found"
  fi
}

# ── Stage minimal flash_rt/ tree ───────────────────────────────────
stage_flash_rt() {
  local dst="${BUNDLE_DIR}/flash_rt"
  rm -rf "${dst}"
  mkdir -p "${dst}"

  _cp() { local rel="$1"; mkdir -p "${dst}/$(dirname "${rel}")"; cp -a "${SRC}/${rel}" "${dst}/${rel}"; }

  # BUNDLE_VERSION
  cat > "${dst}/BUNDLE_VERSION" <<EOF
flashrt_commit=${git_commit}
flashrt_tag=${git_commit}
flashrt_abi=${flashrt_abi}
source_repo=${REPO_ROOT}
EOF

  # Minimal __init__ (no api.py import — Higgs uses frontend directly)
  echo '"""Higgs Audio v3 bundle — minimal flash_rt init."""' > "${dst}/__init__.py"

  _cp models/__init__.py

  # Higgs model pipeline + codec
  mkdir -p "${dst}/models/higgs_audio_v3/_codec"
  for rel in __init__.py pipeline_rtx.py codec.py; do
    cp -a "${SRC}/models/higgs_audio_v3/${rel}" "${dst}/models/higgs_audio_v3/${rel}"
  done
  for rel in __init__.py env_guard.py tokenizer_model.py tokenizer_config.json; do
    cp -a "${SRC}/models/higgs_audio_v3/_codec/${rel}" "${dst}/models/higgs_audio_v3/_codec/${rel}"
  done

  # Frontends
  _cp frontends/__init__.py
  _cp frontends/torch/__init__.py
  for rel in higgs_audio_v3_rtx.py _higgs_audio_v3_fp8.py _higgs_audio_v3_bf16.py; do
    _cp "frontends/torch/${rel}"
  done

  # Hardware (rtx attention backends)
  _cp hardware/__init__.py
  mkdir -p "${dst}/hardware/rtx"
  for rel in attn_backend.py attn_backend_qwen3.py; do
    [[ -f "${SRC}/hardware/rtx/${rel}" ]] && cp -a "${SRC}/hardware/rtx/${rel}" "${dst}/hardware/rtx/${rel}"
  done
  cat > "${dst}/hardware/rtx/__init__.py" << 'PY'
from .attn_backend_qwen3 import RtxFlashAttnBackendQwen3
from .attn_backend import RtxFlashAttnBackend
PY

  # Core (cuda_buffer + utils/hardware)
  _cp core/cuda_buffer.py
  mkdir -p "${dst}/core/utils"
  for f in "${SRC}/core/utils/"*.py; do
    [[ -f "$f" ]] && cp -a "$f" "${dst}/core/utils/"
  done
  touch "${dst}/core/__init__.py" "${dst}/core/utils/__init__.py" 2>/dev/null || true

  find "${dst}" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
  find "${dst}" -name '*.so' -type f -delete 2>/dev/null || true

  log "Staged flash_rt/ ($(find "${dst}" -type f | wc -l) files)"
}

stage_runtime
stage_flash_rt
log "Bundle ready: ${BUNDLE_DIR}"
log "  flashcli bundle validate ${BUNDLE_DIR}"
