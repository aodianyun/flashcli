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

# Mirror endpoints (defaults mirror flashcli_bundle.runtime.mirror).
MIRROR_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple/"
MIRROR_PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn"
MIRROR_HF_ENDPOINT="https://hf-mirror.com"
DEFAULT_GIT_PROXY_PREFIX="https://gh-proxy.com/"
PIP_MIRROR_CHOICE="${FLASHCLI_PIP_MIRROR:-}"
PIP_MIRROR_PROBE="${FLASHCLI_PIP_MIRROR_PROBE:-0}"
case "${FLASHCLI_USE_MIRROR:-0}" in 1|true|yes|on) MIRROR=1 ;; esac

info() { printf '[i] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

set_pip_mirror() {
  case "$1" in
    tuna)    MIRROR_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple/";          MIRROR_PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn" ;;
    aliyun)  MIRROR_PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/";            MIRROR_PIP_TRUSTED_HOST="mirrors.aliyun.com" ;;
    tencent) MIRROR_PIP_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple/";     MIRROR_PIP_TRUSTED_HOST="mirrors.cloud.tencent.com" ;;
    ustc)    MIRROR_PIP_INDEX_URL="https://mirrors.ustc.edu.cn/pypi/web/simple/";       MIRROR_PIP_TRUSTED_HOST="mirrors.ustc.edu.cn" ;;
    huawei)  MIRROR_PIP_INDEX_URL="https://mirrors.huaweicloud.com/repository/pypi/simple/"; MIRROR_PIP_TRUSTED_HOST="mirrors.huaweicloud.com" ;;
    pypi)    MIRROR_PIP_INDEX_URL="https://pypi.org/simple/";                           MIRROR_PIP_TRUSTED_HOST="pypi.org" ;;
    *) warn "unknown --pip-mirror $1 (tuna|aliyun|tencent|ustc|huawei|pypi)"; return 1 ;;
  esac
  return 0
}

probe_pip_mirror() {
  have_cmd curl || return 0
  _best=""; _best_speed=0
  for _label in tuna aliyun tencent ustc huawei; do
    set_pip_mirror "$_label" || continue
    _sp="$(curl -sS -o /dev/null -w '%{speed_download}' --max-time 10 "${MIRROR_PIP_INDEX_URL}numpy/" 2>/dev/null || echo 0)"
    _sp="${_sp%%.*}"; [ -z "$_sp" ] && _sp=0
    if [ "$_sp" -gt "$_best_speed" ]; then _best_speed="$_sp"; _best="$_label"; fi
  done
  [ -n "$_best" ] && set_pip_mirror "$_best" || true
  [ -n "$_best" ] && info "pip mirror probe → ${_best} (${_best_speed} B/s)"
  return 0
}

apply_mirror_endpoints() {
  [ "$MIRROR" = 1 ] || return 0
  [ -n "$PIP_MIRROR_CHOICE" ] && set_pip_mirror "$PIP_MIRROR_CHOICE" || true
  case "${PIP_MIRROR_PROBE:-0}" in 1|true|yes|on) [ -z "$PIP_MIRROR_CHOICE" ] && probe_pip_mirror ;; esac
  export PIP_INDEX_URL="${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
  export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-$MIRROR_PIP_TRUSTED_HOST}"
  export HF_ENDPOINT="${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
  export FLASHCLI_PREFER_HF_MIRROR=1
  case "${FLASHCLI_GIT_PROXY:-}" in
    0|false|no|off) ;;
    *) export FLASHCLI_GIT_PROXY="${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}" ;;
  esac
  info "mirror: PIP_INDEX_URL=${PIP_INDEX_URL}"
  info "mirror: HF_ENDPOINT=${HF_ENDPOINT}"
  [ -n "${FLASHCLI_GIT_PROXY:-}" ] && info "mirror: FLASHCLI_GIT_PROXY=${FLASHCLI_GIT_PROXY}"
  return 0
}

usage() {
  if [ -f "$0" ]; then sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; else
    echo "usage: install.sh [--mirror|--gitee] [--github] [--no-mirror] [--pip-mirror NAME] [--pip-probe] [--from-source] [--ref REF|--branch REF] [--version V] [--dir DIR] [--source-dir DIR]"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mirror|--gitee) MIRROR=1; shift ;;
    --github) MIRROR=0; shift ;;
    --global|--no-mirror) MIRROR=0; shift ;;
    --pip-mirror|--pypi-mirror) PIP_MIRROR_CHOICE="$2"; MIRROR=1; shift 2 ;;
    --pip-probe) PIP_MIRROR_PROBE=1; shift ;;
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
  apply_mirror_endpoints
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
  base=""; api=""
  case "$REPO" in
    *gitee*) base="https://gitee.com/aodiansoft/flashcli/releases/download"; api="https://gitee.com/api/v5/repos/aodiansoft/flashcli/releases/latest" ;;
    *)       base="https://github.com/aodianyun/flashcli/releases/download"; api="https://api.github.com/repos/aodianyun/flashcli/releases/latest" ;;
  esac
  if [ -z "$VERSION" ]; then
    tmpj="$(mktemp)"
    if ! fetch "$api" "$tmpj" 2>/dev/null; then
      rm -f "$tmpj"
      die "no release found for $REPO (and no --version). Publish the release for this source, or re-run with --from-source."
    fi
    VERSION="$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' "$tmpj" | head -1)"
    rm -f "$tmpj"
  fi
  [ -n "$VERSION" ] || die "could not resolve a release version (pass --version or use --from-source)"
  info "installing flashcli $VERSION from release assets"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  fetch "${base}/v${VERSION}/${asset}" "$tmp/$asset" \
    || die "release asset not found: ${base}/v${VERSION}/${asset} (publish it for this source, or use --from-source)"
  fetch "${base}/v${VERSION}/sha256sums.txt" "$tmp/sha256sums.txt" \
    || die "release checksums not found: ${base}/v${VERSION}/sha256sums.txt"
  want="$(awk -v a="$asset" '$2==a {print $1}' "$tmp/sha256sums.txt" | head -1)"
  [ -n "$want" ] || die "$asset not listed in sha256sums.txt"
  have="$($SHA "$tmp/$asset" | awk '{print $1}')"
  [ "$have" = "$want" ] || die "checksum mismatch for $asset (have $have, want $want)"
  install -m 0755 "$tmp/$asset" "$INSTALL_DIR/flashcli"
  info "installed $INSTALL_DIR/flashcli ($VERSION)"
}

if [ "$FROM_SOURCE" = 1 ]; then install_source; else install_release; fi

home="${FLASHCLI_HOME:-$HOME/.flashcli}"
mkdir -p "$home" 2>/dev/null || true
{
  if [ -n "$SOURCE_USED" ] && [ -f "$SOURCE_USED/flashcli-bundle/pyproject.toml" ]; then
    echo "FLASHCLI_BUNDLE_PIP_SPEC=$SOURCE_USED/flashcli-bundle[infer]"
  else
    echo "FLASHCLI_INSTALL_REPO=$REPO"
    echo "FLASHCLI_INSTALL_REF=$REF"
  fi
} > "$home/install.env"
info "Wrote $home/install.env"

if [ "$MIRROR" = 1 ]; then
  {
    echo "FLASHCLI_USE_MIRROR=1"
    echo "PIP_INDEX_URL=${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
    echo "PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST:-$MIRROR_PIP_TRUSTED_HOST}"
    echo "HF_ENDPOINT=${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
    echo "FLASHCLI_PREFER_HF_MIRROR=1"
    echo "FLASHCLI_GIT_PROXY=${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}"
  } > "$home/mirror.env"
  info "Wrote $home/mirror.env (run/serve use mirrors: pip/HF/GitHub)"
fi

echo "[ok] flashcli -> $INSTALL_DIR/flashcli"
case ":$PATH:" in *":$INSTALL_DIR:"*) ;; *) echo "[i] add $INSTALL_DIR to PATH" ;; esac
