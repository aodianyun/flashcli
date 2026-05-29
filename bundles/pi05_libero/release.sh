#!/usr/bin/env bash
# One-command pi05_libero CDN release (see scripts/release_bundle.sh).
#
#   bash release.sh
#   bash release.sh --git-ref main --clean
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

exec bash "${FLASHCLI_ROOT}/scripts/release_bundle.sh" --bundle pi05_libero "$@"
