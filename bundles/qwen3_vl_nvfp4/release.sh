#!/usr/bin/env bash
# One-command FlashHub release (see scripts/release_bundle.sh).
#
#   bash release.sh
#   bash release.sh --clean
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

exec bash "${FLASHCLI_ROOT}/scripts/release_bundle.sh" --bundle qwen3_vl_nvfp4 "$@"
