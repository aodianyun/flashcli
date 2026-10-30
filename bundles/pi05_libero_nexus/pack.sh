#!/usr/bin/env bash
# Native-only v4 pack: manifest + runtime/<dir>/ (substrate + calib + bin).
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${BUNDLE_DIR}/../../scripts/pack_bundle.sh" --bundle-dir "${BUNDLE_DIR}" "$@"
