#!/bin/sh
# flashcli installer — installs the Go host binary (`flashcli`).
#
# Strategy:
#   1. Prefer building from source when a checkout (+ Go) is available
#      (current dir is a checkout, --source-dir, or git can clone it).
#   2. Otherwise download release assets: flashcli-<os>-<arch> + sha256sums.txt.
# Always writes ~/.flashcli/install.env so bundle venvs can install
# flashcli-bundle[infer].
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
#   ./install.sh [--mirror] [--ref REF] [--version V] [--dir DIR] [--source-dir DIR] [--skip-build]
#
# Env: FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF, FLASHCLI_GO_VERSION,
#      FLASHCLI_GO_INSTALL_DIR, FLASHCLI_SOURCE_DIR, FLASHCLI_CLONE_DIR,
#      FLASHCLI_HOME, PIP_INDEX_URL, HF_ENDPOINT
set -eu

REPO_GITHUB="https://github.com/aodianyun/flashcli.git"
REPO_GITEE="https://gitee.com/aodiansoft/flashcli.git"
REPO="${FLASHCLI_INSTALL_REPO:-$REPO_GITHUB}"
REF="${FLASHCLI_INSTALL_REF:-main}"
VERSION="${FLASHCLI_GO_VERSION:-}"
SOURCE_DIR="${FLASHCLI_SOURCE_DIR:-}"
CLONE_DIR="${FLASHCLI_CLONE_DIR:-/opt/flashcli}"
MIRROR=0
SKIP_BUILD=0
INSTALL_DIR="${FLASHCLI_GO_INSTALL_DIR:-}"

usage() {
  sed -n '2,18p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mirror|--gitee) MIRROR=1; shift ;;
    --github) MIRROR=0; shift ;;
    --ref) REF="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$MIRROR" = 1 ]; then
  REPO="${FLASHCLI_INSTALL_REPO:-$REPO_GITEE}"
  export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
fi

if [ -z "$INSTALL_DIR" ]; then
  if [ -w /usr/local/bin ] 2>/dev/null; then INSTALL_DIR=/usr/local/bin; else INSTALL_DIR="$HOME/.local/bin"; fi
fi
mkdir -p "$INSTALL_DIR"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$arch" in x86_64|amd64) goarch=amd64 ;; aarch64|arm64) goarch=arm64 ;; *) echo "unsupported arch: $arch" >&2; exit 1 ;; esac
asset="flashcli-${os}-${goarch}"

fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
  else echo "error: curl or wget required" >&2; exit 1; fi
}

install_from_source() {
  [ "$SKIP_BUILD" = 1 ] && return 1
  command -v go >/dev/null 2>&1 || return 1
  src="$1"
  [ -n "$src" ] && [ -f "$src/scripts/build_go.sh" ] || return 1
  echo "[i] building flashcli from $src"
  ( cd "$src" && bash scripts/build_go.sh >/dev/null )
  [ -f "$src/dist/go/$asset" ] || return 1
  install -m 0755 "$src/dist/go/$asset" "$INSTALL_DIR/flashcli"
  SOURCE_USED="$src"
  return 0
}

# 1) Locate or clone a source checkout.
if [ -z "$SOURCE_DIR" ]; then
  if [ -f "./go/cmd/flashcli/main.go" ] && [ -f "./scripts/build_go.sh" ]; then SOURCE_DIR="$(pwd)";
  elif [ -f "$0" ]; then
    d="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
    if [ -n "$d" ] && [ -f "$d/go/cmd/flashcli/main.go" ]; then SOURCE_DIR="$d"; fi
  fi
fi
if [ -z "$SOURCE_DIR" ] && command -v git >/dev/null 2>&1; then
  if [ ! -f "$CLONE_DIR/scripts/build_go.sh" ]; then
    echo "[i] cloning $REPO (ref $REF) -> $CLONE_DIR"
    git clone --depth 1 --branch "$REF" "$REPO" "$CLONE_DIR" 2>/dev/null || git clone "$REPO" "$CLONE_DIR"
  fi
  SOURCE_DIR="$CLONE_DIR"
fi

SOURCE_USED=""
if install_from_source "$SOURCE_DIR"; then
  echo "[ok] installed $INSTALL_DIR/flashcli (built from $SOURCE_USED)"
else
  # 2) Release assets.
  base=""
  api=""
  case "$REPO" in
    *gitee*) base="https://gitee.com/aodiansoft/flashcli/releases/download"; api="https://gitee.com/api/v5/repos/aodiansoft/flashcli/releases/latest" ;;
    *)       base="https://github.com/aodianyun/flashcli/releases/download"; api="https://api.github.com/repos/aodianyun/flashcli/releases/latest" ;;
  esac
  if [ -z "$VERSION" ]; then
    fetch "$api" /tmp/flashcli-release.json 2>/dev/null || { echo "error: cannot resolve latest release; pass --version" >&2; exit 1; }
    VERSION="$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' /tmp/flashcli-release.json | head -1)"
    rm -f /tmp/flashcli-release.json
  fi
  [ -n "$VERSION" ] || { echo "error: empty version" >&2; exit 1; }
  echo "[i] installing flashcli $VERSION from release assets"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  fetch "${base}/v${VERSION}/${asset}" "$tmp/$asset"
  fetch "${base}/v${VERSION}/sha256sums.txt" "$tmp/sha256sums.txt"
  want="$(awk -v a="$asset" '$2==a {print $1}' "$tmp/sha256sums.txt" | head -1)"
  [ -n "$want" ] || { echo "error: $asset not in sha256sums.txt" >&2; exit 1; }
  if command -v sha256sum >/dev/null 2>&1; then have="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
  else have="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"; fi
  [ "$have" = "$want" ] || { echo "error: checksum mismatch for $asset" >&2; exit 1; }
  install -m 0755 "$tmp/$asset" "$INSTALL_DIR/flashcli"
  echo "[ok] installed $INSTALL_DIR/flashcli"
fi

# 3) Persist the bundle-venv source for flashcli-bundle[infer].
home="${FLASHCLI_HOME:-$HOME/.flashcli}"
mkdir -p "$home" 2>/dev/null || true
if [ -n "$SOURCE_USED" ] && [ -f "$SOURCE_USED/flashcli-bundle/pyproject.toml" ]; then
  echo "export FLASHCLI_BUNDLE_PIP_SPEC=$SOURCE_USED/flashcli-bundle[infer]" > "$home/install.env"
else
  {
    echo "export FLASHCLI_INSTALL_REPO=$REPO"
    echo "export FLASHCLI_INSTALL_REF=$REF"
  } > "$home/install.env"
fi

echo "[i] flashcli -> $INSTALL_DIR/flashcli ; wrote $home/install.env"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "[i] add $INSTALL_DIR to PATH" ;; esac
