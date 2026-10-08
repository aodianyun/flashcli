#!/bin/sh
# flashcli installer — installs the Go host binary (`flashcli`).
#
# Default: download release assets (flashcli-<os>-<arch> + sha256sums.txt).
#   -> requires only curl/wget + a sha256 tool (+ ca-certificates). No Go.
# Source:  pass --from-source (or --source-dir DIR) to clone + build with Go.
#   -> requires git + Go (auto-installed when possible).
# Missing system tools are detected and installed via the OS package manager
# (apt/dnf/yum/apk/zypper) when running as root; otherwise it prints hints.
# Always writes ~/.flashcli/install.env for bundle venvs (flashcli-bundle[infer]).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
#   ./install.sh                       # release
#   ./install.sh --from-source --branch dev
#   ./install.sh --version 1.2.3 --dir /usr/local/bin
#
# Env: FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF, FLASHCLI_GO_VERSION,
#      FLASHCLI_GO_INSTALL_DIR, FLASHCLI_SOURCE_DIR, FLASHCLI_CLONE_DIR,
#      FLASHCLI_HOME, FLASHCLI_SKIP_APT_OS_PACKAGES=1, PIP_INDEX_URL, HF_ENDPOINT
set -eu

REPO_GITHUB="https://github.com/aodianyun/flashcli.git"
REPO_GITEE="https://gitee.com/aodiansoft/flashcli.git"
REPO="${FLASHCLI_INSTALL_REPO:-$REPO_GITHUB}"
REF="${FLASHCLI_INSTALL_REF:-main}"
VERSION="${FLASHCLI_GO_VERSION:-}"
SOURCE_DIR="${FLASHCLI_SOURCE_DIR:-}"
CLONE_DIR="${FLASHCLI_CLONE_DIR:-/opt/flashcli}"
INSTALL_DIR="${FLASHCLI_GO_INSTALL_DIR:-}"
MIRROR=0
FROM_SOURCE=0
APT_DISABLED=0

info() { printf '[i] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

usage() {
  if [ -f "$0" ]; then sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; else
    echo "usage: install.sh [--mirror] [--from-source] [--ref REF|--branch REF] [--version V] [--dir DIR] [--source-dir DIR]"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mirror|--gitee) MIRROR=1; shift ;;
    --github) MIRROR=0; shift ;;
    --ref|--branch) REF="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --from-source|--source) FROM_SOURCE=1; shift ;;
    --source-dir) FROM_SOURCE=1; SOURCE_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
[ -n "$SOURCE_DIR" ] && FROM_SOURCE=1

if [ "$MIRROR" = 1 ]; then
  REPO="${FLASHCLI_INSTALL_REPO:-$REPO_GITEE}"
  export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
fi

if [ -z "$INSTALL_DIR" ]; then
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] && [ -w /usr/local/bin ] 2>/dev/null; then
    INSTALL_DIR=/usr/local/bin
  else
    INSTALL_DIR="$HOME/.local/bin"
  fi
fi
mkdir -p "$INSTALL_DIR"

# ---- OS package auto-install (mirrors the legacy installer) ----------------
_apt_backup_once() {
  [ -f /etc/apt/sources.list ] && [ ! -f /etc/apt/sources.list.flashcli-bak ] \
    && cp -a /etc/apt/sources.list /etc/apt/sources.list.flashcli-bak 2>/dev/null || true
}
_apt_rewrite() {
  _f="$1"; [ -f "$_f" ] || return 0
  sed -i \
    -e 's|https\?://archive\.ubuntu\.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' \
    -e 's|https\?://security\.ubuntu\.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' \
    -e 's|https\?://deb\.debian\.org/debian/|https://mirrors.aliyun.com/debian/|g' \
    -e 's|https\?://security\.debian\.org/debian-security/|https://mirrors.aliyun.com/debian-security/|g' \
    "$_f" 2>/dev/null || true
}
apply_apt_mirror() {
  [ "$MIRROR" = 1 ] || return 0
  have_cmd apt-get || return 0
  _apt_backup_once
  info "mirror: switching apt sources -> mirrors.aliyun.com"
  for _f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    _apt_rewrite "$_f"
  done
}
install_os_packages() {
  [ $# -gt 0 ] || return 1
  [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] || return 1
  case "${FLASHCLI_SKIP_APT_OS_PACKAGES:-0}" in 1|true|yes|on) return 1 ;; esac
  [ "$APT_DISABLED" = 1 ] && return 1
  apply_apt_mirror
  if have_cmd apt-get; then
    info "installing OS packages (apt): $*"
    apt-get update -qq 2>/dev/null || true
    apt-get install -y "$@" && return 0
    APT_DISABLED=1; return 1
  fi
  if have_cmd dnf; then info "installing OS packages (dnf): $*"; dnf install -y "$@" && return 0; fi
  if have_cmd yum; then info "installing OS packages (yum): $*"; yum install -y "$@" && return 0; fi
  if have_cmd apk; then info "installing OS packages (apk): $*"; apk add --no-cache "$@" && return 0; fi
  if have_cmd zypper; then info "installing OS packages (zypper): $*"; zypper --non-interactive install "$@" && return 0; fi
  return 1
}
tool_hint() {
  printf '  Debian/Ubuntu: apt install -y %s\n  RHEL/Fedora:   dnf install -y %s\n  Alpine:        apk add %s\n' "$1" "$1" "$1" >&2
}

ensure_download_tool() {
  have_cmd curl && { DL=curl; return 0; }
  have_cmd wget && { DL=wget; return 0; }
  warn "curl/wget not found — installing ..."
  install_os_packages curl || install_os_packages wget || true
  have_cmd curl && { DL=curl; return 0; }
  have_cmd wget && { DL=wget; return 0; }
  die "curl or wget is required"; tool_hint curl
}
fetch() {
  if [ "$DL" = curl ]; then curl -fsSL "$1" -o "$2"; else wget -qO "$2" "$1"; fi
}
ensure_sha256_tool() {
  have_cmd sha256sum && { SHA=sha256sum; return 0; }
  have_cmd shasum && { SHA="shasum -a 256"; return 0; }
  warn "sha256 tool not found — installing coreutils ..."
  install_os_packages coreutils || true
  have_cmd sha256sum && { SHA=sha256sum; return 0; }
  have_cmd shasum && { SHA="shasum -a 256"; return 0; }
  die "need sha256sum or shasum to verify downloads"; tool_hint coreutils
}
ensure_git() {
  have_cmd git && return 0
  warn "git not found — installing ..."
  install_os_packages git || true
  have_cmd git || { die "git is required for --from-source"; tool_hint git; }
}
ensure_go() {
  have_cmd go && return 0
  warn "Go not found — installing ..."
  install_os_packages golang-go || install_os_packages golang || true
  have_cmd go && return 0
  gover="${FLASHCLI_GO_TOOLCHAIN_VERSION:-1.24.0}"
  dest="${FLASHCLI_GO_ROOT:-$HOME/.local}"; mkdir -p "$dest"
  if [ "$MIRROR" = 1 ]; then gbase="https://mirrors.aliyun.com/golang"; else gbase="https://go.dev/dl"; fi
  tgz="$dest/go${gover}.linux-${goarch}.tar.gz"
  info "downloading Go ${gover} -> $dest"
  fetch "${gbase}/go${gover}.linux-${goarch}.tar.gz" "$tgz"
  tar -C "$dest" -xzf "$tgz" && rm -f "$tgz"
  export PATH="$dest/go/bin:$PATH"
  have_cmd go || die "failed to provision Go; install Go >= 1.24 and re-run"; 
}

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$arch" in x86_64|amd64) goarch=amd64 ;; aarch64|arm64) goarch=arm64 ;; *) die "unsupported arch: $arch" ;; esac
asset="flashcli-${os}-${goarch}"

SOURCE_USED=""
install_source() {
  ensure_git
  if [ -z "$SOURCE_DIR" ]; then
    SOURCE_DIR="$CLONE_DIR"
    if [ ! -f "$SOURCE_DIR/scripts/build_go.sh" ]; then
      info "cloning $REPO (ref $REF) -> $SOURCE_DIR"
      git clone --depth 1 --branch "$REF" "$REPO" "$SOURCE_DIR" 2>/dev/null || git clone "$REPO" "$SOURCE_DIR"
    fi
  fi
  [ -f "$SOURCE_DIR/scripts/build_go.sh" ] || die "not a flashcli source checkout: $SOURCE_DIR"
  ensure_go
  info "building flashcli from $SOURCE_DIR"
  ( cd "$SOURCE_DIR" && bash scripts/build_go.sh >/dev/null )
  [ -f "$SOURCE_DIR/dist/go/$asset" ] || die "build did not produce $SOURCE_DIR/dist/go/$asset"
  install -m 0755 "$SOURCE_DIR/dist/go/$asset" "$INSTALL_DIR/flashcli"
  SOURCE_USED="$SOURCE_DIR"
  info "installed $INSTALL_DIR/flashcli (built from $SOURCE_USED)"
}

install_release() {
  ensure_download_tool
  ensure_sha256_tool
  GH_B="https://github.com/aodianyun/flashcli/releases/download"
  GH_A="https://api.github.com/repos/aodianyun/flashcli/releases/latest"
  GE_B="https://gitee.com/aodiansoft/flashcli/releases/download"
  GE_A="https://gitee.com/api/v5/repos/aodiansoft/flashcli/releases/latest"
  case "$REPO" in
    *gitee*) FIRST_B="$GE_B"; FIRST_A="$GE_A"; SECOND_B="$GH_B"; SECOND_A="$GH_A" ;;
    *)       FIRST_B="$GH_B"; FIRST_A="$GH_A"; SECOND_B="$GE_B"; SECOND_A="$GE_A" ;;
  esac
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  if try_release "$FIRST_B" "$FIRST_A"; then return 0; fi
  if try_release "$SECOND_B" "$SECOND_A"; then return 0; fi
  die "no release found (and no --version). Build from source instead: re-run with --from-source"
}

try_release() {
  base="$1"; api="$2"; ver="$VERSION"
  [ -n "$REPO" ] || return 1
  if [ -z "$ver" ]; then
    if ! fetch "$api" "$tmp/release.json" 2>/dev/null; then return 1; fi
    ver="$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' "$tmp/release.json" | head -1)"
  fi
  [ -n "$ver" ] || return 1
  if ! fetch "${base}/v${ver}/${asset}" "$tmp/$asset" 2>/dev/null; then return 1; fi
  if ! fetch "${base}/v${ver}/sha256sums.txt" "$tmp/sha256sums.txt" 2>/dev/null; then return 1; fi
  want="$(awk -v a="$asset" '$2==a {print $1}' "$tmp/sha256sums.txt" | head -1)"
  [ -n "$want" ] || return 1
  have="$($SHA "$tmp/$asset" | awk '{print $1}')"
  [ "$have" = "$want" ] || { warn "checksum mismatch for $asset (have $have, want $want)"; return 1; }
  install -m 0755 "$tmp/$asset" "$INSTALL_DIR/flashcli"
  info "installed $INSTALL_DIR/flashcli ($ver)"
  return 0
}

if [ "$FROM_SOURCE" = 1 ]; then install_source; else install_release; fi

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

echo "[ok] flashcli -> $INSTALL_DIR/flashcli ; wrote $home/install.env"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "[i] add $INSTALL_DIR to PATH" ;; esac
