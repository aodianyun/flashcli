#!/usr/bin/env bash
# Thin wrapper → _bundle_build.sh (matches existing bundle convention).
#
#   bash build.sh --repo-root /app/FlashRT --nexus-src /app/FlashRT-Nexus
#   bash build.sh --pack-only
#
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${BUNDLE_DIR}/_bundle_build.sh" "$@"
