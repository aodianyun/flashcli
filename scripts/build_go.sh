#!/usr/bin/env bash
# Build flashcli-go release binaries + sha256sums.
#
# Usage: bash scripts/build_go.sh [OUT_DIR]
#
# Version is single-sourced from root pyproject.toml [project].version and
# injected via -ldflags. Produces:
#   dist/go/flashcli-<os>-<arch>
#   dist/go/sha256sums.txt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/go}"
GO_PKG="github.com/aodianyun/flashcli/go/internal/version.Version"

read_version() {
  # Do not depend on Python here: source installs run on minimal Ubuntu images
  # where python3 may not be installed. pyproject.toml keeps one [project]
  # version line, so a shell/awk parse is sufficient.
  sed -n 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$ROOT/pyproject.toml" | head -1
}

VERSION="$(read_version)"
if [ -z "$VERSION" ]; then
  echo "error: empty version" >&2
  exit 1
fi
echo "flashcli-go version: $VERSION"

mkdir -p "$OUT"
targets=("${FLASHCLI_GO_TARGETS:-linux/amd64 linux/arm64}")
for target in ${targets[*]}; do
  goos="${target%%/*}"
  goarch="${target##*/}"
  for cmd in flashcli flashserver; do
    name="${cmd}-${goos}-${goarch}"
    echo "building $name ..."
    ( cd "$ROOT/go" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
        go build -trimpath -ldflags "-s -w -X ${GO_PKG}=${VERSION}" \
        -o "$OUT/$name" "./cmd/$cmd" )
  done
  setup_name="flashserver-setup-${goos}-${goarch}"
  [ "$goos" = "windows" ] && setup_name="${setup_name}.exe"
  echo "building $setup_name ..."
  ( cd "$ROOT/go" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
      go build -trimpath -ldflags "-s -w -X ${GO_PKG}=${VERSION}" \
      -o "$OUT/$setup_name" ./cmd/flashserver-setup )
done

# Windows setup needs the Linux binaries in its asset directory; build the
# Windows installer for the default release architecture as well.
for target in ${FLASHCLI_SETUP_WINDOWS_TARGETS:-windows/amd64}; do
  goos="${target%%/*}"
  goarch="${target##*/}"
  name="flashserver-setup-${goos}-${goarch}.exe"
  echo "building $name ..."
  ( cd "$ROOT/go" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
      go build -trimpath -ldflags "-s -w -X ${GO_PKG}=${VERSION}" \
      -o "$OUT/$name" ./cmd/flashserver-setup )
done

if command -v sha256sum >/dev/null 2>&1; then
  sha_cmd=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  sha_cmd=(shasum -a 256)
else
  echo "error: neither sha256sum nor shasum is available" >&2
  exit 1
fi
( cd "$OUT" && "${sha_cmd[@]}" flashcli-* flashserver-* > sha256sums.txt )
echo "artifacts in $OUT:"
ls -1 "$OUT"
