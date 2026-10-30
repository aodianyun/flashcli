#!/usr/bin/env bash
# v4 pack: manifest + entry + minimal flash_rt + selected runtime cell.
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${BUNDLE_DIR}/../../scripts/pack_bundle.sh" --bundle-dir "${BUNDLE_DIR}" "$@"
