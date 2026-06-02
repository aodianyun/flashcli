#!/usr/bin/env bash
# Thin wrapper → scripts/pack_bundle.sh
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
exec bash "${FLASHCLI_ROOT}/scripts/pack_bundle.sh" --bundle-dir "${BUNDLE_DIR}" "$@"
