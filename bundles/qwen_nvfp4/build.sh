#!/usr/bin/env bash
# Assemble unified Qwen NVFP4 bundle (Qwen3-8B + Qwen3.6-27B) from FlashRT.
#
#   bash build.sh --repo-root /app/FlashRT
#   bash build.sh --pack-only
#
# Release zip (cu130 × py310/311/312):
#   bash ../../scripts/build_qwen_release_matrix.sh
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

exec bash "${FLASHCLI_ROOT}/scripts/build_qwen_bundle.sh" \
  --bundle-dir "${BUNDLE_DIR}" \
  --variant all \
  "$@"
