#!/usr/bin/env bash
# Local dev: single-environment bundle build (not used by release matrix).
#
#   bash build.sh --repo-root /path/to/FlashRT
#   bash build.sh --pack-only
#
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${BUNDLE_DIR}/_bundle_build.sh" "$@"
