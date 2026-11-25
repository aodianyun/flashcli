#!/usr/bin/env bash
# Build only the Linux/amd64 binaries used by local acceptance tests.
#
# This is the development counterpart of scripts/build_go.sh. Do not build
# release assets (arm64, Windows setup) just to run tests: it wastes time and
# none of those binaries are used by pytest.
#
# Usage:
#   bash scripts/build_dev_bins.sh [OUT_DIR]
#   GO=/path/to/go bash scripts/build_dev_bins.sh
#
# Output: dist/go/flashcli-linux-amd64 and dist/go/flashserver-linux-amd64.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/go}"
GO="${GO:-go}"
GO_PKG="github.com/aodianyun/flashcli/go/internal/version.Version"

VERSION="$(sed -n 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$ROOT/pyproject.toml" | head -1)"
if [ -z "$VERSION" ]; then
  echo "error: empty version in pyproject.toml" >&2
  exit 1
fi

mkdir -p "$OUT"
for cmd in flashcli flashserver; do
  name="${cmd}-linux-amd64"
  echo "building $name ..."
  ( cd "$ROOT/go" && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
      "$GO" build -trimpath -buildvcs=false \
      -ldflags "-X ${GO_PKG}=${VERSION}" \
      -o "$OUT/$name" "./cmd/$cmd" )
done

ls -l "$OUT/flashcli-linux-amd64" "$OUT/flashserver-linux-amd64"
