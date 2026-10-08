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
  python3 - "$ROOT/pyproject.toml" <<'PY'
import sys
path = sys.argv[1]
try:
    import tomllib
    with open(path, "rb") as fh:
        print(tomllib.load(fh)["project"]["version"])
except Exception:
    try:
        import tomli as tomllib
        with open(path, "rb") as fh:
            print(tomllib.load(fh)["project"]["version"])
    except Exception:
        import re
        text = open(path, encoding="utf-8").read()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        if not m:
            raise SystemExit("cannot determine version from pyproject.toml")
        print(m.group(1))
PY
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
  name="flashcli-${goos}-${goarch}"
  echo "building $name ..."
  ( cd "$ROOT/go" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
      go build -trimpath -ldflags "-s -w -X ${GO_PKG}=${VERSION}" \
      -o "$OUT/$name" ./cmd/flashcli )
done

( cd "$OUT" && sha256sum flashcli-* > sha256sums.txt )
echo "artifacts in $OUT:"
ls -1 "$OUT"
