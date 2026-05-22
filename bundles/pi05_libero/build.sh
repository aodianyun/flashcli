#!/usr/bin/env bash
# Assemble this bundle from FlashRT source (Linux + NVIDIA GPU).
#
#   bash build.sh
#   bash build.sh --pack-only --repo-root /app/FlashRT
#   bash build.sh --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

exec bash "${FLASHCLI_ROOT}/scripts/build_pi05_bundle.sh" \
  --bundle-dir "${BUNDLE_DIR}" \
  "$@"
