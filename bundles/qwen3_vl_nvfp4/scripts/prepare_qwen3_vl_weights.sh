#!/usr/bin/env bash
# Prepare FlashRT NVFP4 weights for qwen3_vl_nvfp4 (read-only FlashRT quantize tool).
#
#   export FLASHRT_REPO=/path/to/FlashRT
#   bash scripts/prepare_qwen3_vl_weights.sh --dst /tmp/Qwen3-VL-8B-FlashRT-NVFP4
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

SRC_REPO="Qwen/Qwen3-VL-8B-Instruct"
SRC_DIR=""
DST_DIR=""
FLASHRT_REPO=""
HF_REVISION="main"
SKIP_DOWNLOAD=0

log() { printf '[prepare-qwen3-vl-weights] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Download Qwen3-VL-8B-Instruct and quantize to FlashRT NVFP4 layout.

Usage:
  bash bundles/qwen3_vl_nvfp4/scripts/prepare_qwen3_vl_weights.sh [OPTIONS]

Options:
  --dst DIR               Output NVFP4 checkpoint directory (required)
  --src-dir DIR           Existing BF16 checkpoint (skip HF download)
  --flashrt-repo DIR      FlashRT source (default: auto-detect or \$FLASHRT_REPO)
  --hf-repo REPO          Hugging Face source repo (default: ${SRC_REPO})
  --hf-revision REF       HF revision (default: main)
  --skip-download         Require --src-dir; do not call huggingface-cli
  -h, --help
EOF
}

resolve_flashrt_repo() {
  if [[ -n "${FLASHRT_REPO}" ]]; then
    FLASHRT_REPO="$(cd "${FLASHRT_REPO}" && pwd)"
    [[ -f "${FLASHRT_REPO}/tools/quantize_qwen3_vl_nvfp4.py" ]] \
      || die "Missing quantize tool: ${FLASHRT_REPO}/tools/quantize_qwen3_vl_nvfp4.py"
    return
  fi
  local candidate
  for candidate in \
    "${FLASHRT_REPO:-}" \
    "$(cd "${FLASHCLI_ROOT}/.." && pwd)/FlashRT" \
    "$(cd "${FLASHCLI_ROOT}/.." && pwd)"; do
    [[ -n "${candidate}" && -f "${candidate}/tools/quantize_qwen3_vl_nvfp4.py" ]] || continue
    FLASHRT_REPO="$(cd "${candidate}" && pwd)"
    return
  done
  die "Cannot find FlashRT repo; pass --flashrt-repo or set FLASHRT_REPO"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dst) DST_DIR="$2"; shift 2 ;;
    --src-dir) SRC_DIR="$2"; shift 2 ;;
    --flashrt-repo) FLASHRT_REPO="$2"; shift 2 ;;
    --hf-repo) SRC_REPO="$2"; shift 2 ;;
    --hf-revision) HF_REVISION="$2"; shift 2 ;;
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "${DST_DIR}" ]] || die "--dst is required"
resolve_flashrt_repo

if [[ -n "${SRC_DIR}" ]]; then
  SRC_DIR="$(cd "${SRC_DIR}" && pwd)"
elif [[ "${SKIP_DOWNLOAD}" -eq 1 ]]; then
  die "--skip-download requires --src-dir"
else
  command -v huggingface-cli >/dev/null 2>&1 || die "huggingface-cli not found"
  SRC_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qwen3-vl-src.XXXXXX")"
  log "Downloading ${SRC_REPO} (revision=${HF_REVISION}) -> ${SRC_DIR}"
  huggingface-cli download "${SRC_REPO}" --revision "${HF_REVISION}" --local-dir "${SRC_DIR}"
fi

[[ -d "${SRC_DIR}" ]] || die "Source checkpoint not found: ${SRC_DIR}"
mkdir -p "${DST_DIR}"
DST_DIR="$(cd "${DST_DIR}" && pwd)"

log "Quantizing ${SRC_DIR} -> ${DST_DIR}"
python3 "${FLASHRT_REPO}/tools/quantize_qwen3_vl_nvfp4.py" \
  --src "${SRC_DIR}" \
  --dst "${DST_DIR}"

log "Done. NVFP4 checkpoint: ${DST_DIR}"
log "Dev embed: bash bundles/qwen3_vl_nvfp4/build.sh --embed-checkpoint ${DST_DIR}"
log "Release: upload ${DST_DIR} to Hugging Face and update flashcli-bundle.json weights.repo"
