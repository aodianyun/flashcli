#!/bin/sh
# flashcli installer
#
# Auto-detect network (recommended):
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/auto_install.sh | sh -s -- [OPTIONS]
# Examples (restricted network — Gitee + mirror):
#   curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
# Open network (GitHub):
#   curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
#
# Goals:
#   1. Pre-flight: make the host as ready as possible for pyproject.toml [project]
#      (incl. zip/rsync for bundle zip workflows)
#   2. Auto-install python3+pip when missing (root); install flashcli+deps into ~/.flashcli/venv by default
#   3. Post-flight: verify imports, flashcli/hf on PATH, pip check; auto-repair once
#   4. Exit 1 with actionable errors if requirements still cannot be met
#
# Optional env:
#   FLASHCLI_INSTALL_REPO / FLASHCLI_INSTALL_REF   (default: main @ GitHub)
#   FLASHCLI_USE_MIRROR=1   China-friendly mirrors: pip/HF/git + apt/yum/dnf/apk (root)
#   FLASHCLI_PIP_MIRROR=tuna     Pin PyPI (tuna|aliyun|tencent|ustc|huawei|pypi); skips probe
#   FLASHCLI_PIP_MIRROR_PROBE=0  Default: Tsinghua (tuna). Set 1 or use install.sh --pip-probe to benchmark.
#   FLASHCLI_PIP_MIRROR_PROBE_TIMEOUT=30  Per-mirror probe timeout (seconds)
#   FLASHCLI_PIP_MIRROR_PROBE_SAMPLE_BYTES=5242880  Bytes to download per mirror (HTTP Range)
#   FLASHCLI_PIP_MIRROR_PROBE_MIN_BYTES=1048576  Min bytes for a valid throughput sample
#   FLASHCLI_PIP_MIRROR_PROBE_PACKAGE=numpy  PEP 503 project for large-wheel probe
#   FLASHCLI_PIP_FAILOVER=1     With --mirror and no --pip-mirror, try next PyPI mirrors on network/index errors
#   FLASHCLI_OS_MIRROR=0    With --mirror, skip rewriting OS package-manager sources
#   FLASHCLI_GIT_PROXY=URL   GitHub fetch proxy prefix (default https://gh-proxy.com/)
#   FLASHCLI_GIT_TIMEOUT=25  Timeout (seconds) for git ls-remote during preflight
#   FLASHCLI_GIT_RETRIES=3   Retries when git remote probe fails (Gitee rate-limit / 401 jitter)
#   FLASHCLI_GIT_RETRY_SLEEP=2  Seconds between git remote probe retries
#   FLASHCLI_PYTHON
#   FLASHCLI_SKIP_GPU_CHECK=1   skip GPU probe (default: warn if missing, still install)
#   FLASHCLI_REQUIRE_GPU=1      abort install when no NVIDIA GPU (default: install CLI anyway)
#   FLASHCLI_SKIP_APT_OS_PACKAGES=1  never run apt-get/dnf for zip/git/python (host broken repos)
#   FLASHCLI_PIP_USER=auto|0|1
#   FLASHCLI_QUIET=1
#   FLASHCLI_NO_REPAIR=1          skip one automatic pip repair retry
#   FLASHCLI_STRICT_PIP_CHECK=1   fail on any pip check conflict (default: flashcli-only)
#   FLASHCLI_AUTO_INSTALL_PYTHON=0  disable auto OS install of python3+pip+git (default: on when root)
#   FLASHCLI_BREAK_SYSTEM_PACKAGES=1  pass pip --break-system-packages (PEP 668 images)
#   FLASHCLI_USE_VENV=0             skip venv; install to system/user site (default: $FLASHCLI_HOME/venv)
#   FLASHCLI_HOME                   data + venv root (default: ~/.flashcli); mirror.env / install.env / venv
#   FLASHCLI_VENV                   override venv path (default: $FLASHCLI_HOME/venv)

set -eu

DEFAULT_REPO_GITHUB="https://github.com/aodianyun/flashcli.git"
DEFAULT_REPO_GITEE="https://gitee.com/aodiansoft/flashcli.git"
DEFAULT_REPO="$DEFAULT_REPO_GITHUB"
REPO="${FLASHCLI_INSTALL_REPO:-$DEFAULT_REPO}"
REF="${FLASHCLI_INSTALL_REF:-main}"
QUIET="${FLASHCLI_QUIET:-0}"
USE_MIRROR="${FLASHCLI_USE_MIRROR:-0}"
PIP_MIRROR_CHOICE="${FLASHCLI_PIP_MIRROR:-}"
PIP_MIRROR_PROBE="${FLASHCLI_PIP_MIRROR_PROBE:-0}"
RUN_TESTS="${FLASHCLI_RUN_TESTS:-0}"
RUN_CORE_TESTS="${FLASHCLI_RUN_CORE_TESTS:-0}"
REPO_FROM_USER=0
if [ -n "${FLASHCLI_INSTALL_REPO:-}" ]; then
  REPO_FROM_USER=1
fi
# Preserve user-exported PIP_INDEX_URL — auto failover must not override it.
PIP_INDEX_URL_USER_SET=0
if [ -n "${PIP_INDEX_URL:-}" ]; then
  PIP_INDEX_URL_USER_SET=1
fi

# Alternate endpoints when --mirror / FLASHCLI_USE_MIRROR=1 (PyPI default: Tsinghua)
MIRROR_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple/"
MIRROR_PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn"
MIRROR_HF_ENDPOINT="https://hf-mirror.com"
# Only Aliyun hosts get-pip.py reliably; index may come from another mirror.
MIRROR_GET_PIP_URL="https://mirrors.aliyun.com/pypi/get-pip.py"
MIRROR_PIP_LABEL="tuna"
# GitHub HTTPS proxy prefix for git+URL (override with FLASHCLI_GIT_PROXY).
DEFAULT_GIT_PROXY_PREFIX="https://gh-proxy.com/"
PYPI_MIRROR_PROBE_TIMEOUT="${FLASHCLI_PIP_MIRROR_PROBE_TIMEOUT:-30}"
PYPI_MIRROR_PROBE_SAMPLE_BYTES="${FLASHCLI_PIP_MIRROR_PROBE_SAMPLE_BYTES:-5242880}"
PYPI_MIRROR_PROBE_MIN_BYTES="${FLASHCLI_PIP_MIRROR_PROBE_MIN_BYTES:-1048576}"
PYPI_PROBE_PACKAGE="${FLASHCLI_PIP_MIRROR_PROBE_PACKAGE:-numpy}"
OS_MIRRORS_APPLIED=0
APT_OS_PACKAGES_DISABLED=0

# ---------------------------------------------------------------------------
# pyproject.toml [project] — keep in sync with repo pyproject.toml
# ---------------------------------------------------------------------------
REQUIRES_PYTHON_MIN="3.10"
# Minimum pip that can finish install.sh end-to-end with our flag probing:
#   - PEP 508 direct URL + #subdirectory= (flashcli-bundle from git)
#   - new dependency resolver (pip 20.3+); 21.3 is a safe known-good floor
# Optional flags are NOT part of this floor — they are probed at use time:
#   --root-user-action       → pip>=22.1  (never used inside venv)
#   --break-system-packages  → pip>=23.0.1 (only system PEP 668; default path is venv)
# Do NOT raise this to force "newer is better"; only bump when a real install feature requires it.
MIN_PIP_VERSION="21.3"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
# Keep in sync with pyproject.toml [project].dependencies — one spec per line for verify/repair.
# Do NOT space-join specs with commas (e.g. "pkg>=1.0,<2.0" breaks under word-split).
_flashcli_pyproject_deps_list() {
  cat <<'EOF'
typer>=0.12
pyyaml>=6.0
packaging>=23.0
huggingface_hub>=0.26
tqdm>=4.66
EOF
}
# tomli>=2.0 only when python_version < '3.11' (handled in verify script)
# Order: PATH defaults first (/usr/local before /usr), then versioned binaries.
PYTHON_CANDIDATES="python python3 \
  /usr/local/bin/python3 /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
  python3.12 python3.11 python3.10 python3 \
  /usr/bin/python3 /usr/bin/python3.13 /usr/bin/python3.12 python3.13"

info() { [ "$QUIET" = "1" ] || printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
flashcli install.sh — install flashcli from git (default: main @ GitHub).

Usage:
  ./install.sh [OPTIONS]
  curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- [OPTIONS]
  curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh -s -- [OPTIONS]

Options:
  -h, --help              Show this help
  -q, --quiet             Less output
  --ref REF, --branch REF   Git ref (branch/tag/commit). Default: main
  --repo URL, --git-url URL Git remote for pip install (GitHub, Gitee, self-hosted, …)
  --mirror                  Use China-friendly mirrors (default PyPI: Tsinghua; pip/HF/git; root: apt/yum/dnf/apk)
  --pip-probe               With --mirror, benchmark PyPI mirrors (5 MiB sample download; opt-in)
  --pip-mirror, --pypi-mirror NAME  Pin PyPI index (tuna|aliyun|tencent|ustc|huawei|pypi); skips probe
                                    pypi = https://pypi.org/simple/ (works with --mirror for HF/git/OS)
                                    Without pin, --mirror auto-fails over tuna→aliyun→ustc→tencent→huawei
                                    on network/index errors (disable: FLASHCLI_PIP_FAILOVER=0)
  --global, --no-mirror     Disable mirror endpoints (force direct official endpoints)
  --gitee                   Shortcut: --repo https://gitee.com/aodiansoft/flashcli.git
  --github                  Shortcut: --repo https://github.com/aodianyun/flashcli.git
  --run-core-tests          After install, clone source and run core pytest subset
  --run-tests               After install, clone source and run full pytest suite

Environment (override flags):
  FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF
  FLASHCLI_USE_MIRROR=1
  FLASHCLI_PIP_MIRROR=tuna    Pin PyPI (tuna|aliyun|tencent|ustc|huawei|pypi); skips probe
  FLASHCLI_PIP_MIRROR_PROBE=0  Default: Tsinghua. Set 1 or pass --pip-probe to benchmark mirrors.
  FLASHCLI_PIP_MIRROR_PROBE_TIMEOUT=30
  FLASHCLI_PIP_MIRROR_PROBE_SAMPLE_BYTES=5242880
  FLASHCLI_PIP_FAILOVER=1     Auto-try next PyPI mirrors under --mirror when unpinned (0=off)
  FLASHCLI_OS_MIRROR=0      With --mirror, do not rewrite apt/yum/dnf/apk sources
  FLASHCLI_GIT_PROXY=URL    GitHub git proxy prefix (default https://gh-proxy.com/; used as 3rd fallback)
  FLASHCLI_GIT_TIMEOUT=25   git ls-remote timeout during preflight (seconds)
  FLASHCLI_GIT_RETRIES=3    Retries on flaky Gitee/GitHub reachability (rate-limit / 401)
  FLASHCLI_GIT_RETRY_SLEEP=2  Sleep between git remote retries (seconds)
  FLASHCLI_AUTO_INSTALL_PYTHON=0  Disable auto OS install of python3+pip (default: on for root)
  FLASHCLI_HOME=~/.flashcli       Data + CLI venv root (mirror.env, install.env, venv)
  FLASHCLI_VENV=PATH              Override CLI venv (default: $FLASHCLI_HOME/venv)
  FLASHCLI_USE_VENV=0             Install to system/user site instead of $FLASHCLI_HOME/venv
  FLASHCLI_REQUIRE_GPU=1          Abort when no NVIDIA GPU (default: warn and continue)
  FLASHCLI_SKIP_GPU_CHECK=1       Skip GPU probe entirely
  FLASHCLI_RUN_TESTS=1            Same as --run-tests
  FLASHCLI_RUN_CORE_TESTS=1       Same as --run-core-tests
  PIP_INDEX_URL, HF_ENDPOINT  Override mirror defaults

Examples:
  curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
  curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
  ./install.sh --mirror
  ./install.sh --global
  ./install.sh --ref develop
  ./install.sh --mirror --ref main
  ./install.sh --mirror --pip-mirror tuna
  ./install.sh --mirror --pip-mirror pypi
  ./install.sh --pip-mirror aliyun --repo https://gitee.com/aodiansoft/flashcli.git
  ./install.sh --gitee --ref main
  ./install.sh --repo https://gitee.com/aodiansoft/flashcli.git --ref main
  FLASHCLI_USE_MIRROR=1 ./install.sh --repo https://gitee.com/aodiansoft/flashcli.git
EOF
}

mirror_mode_enabled() {
  case "${USE_MIRROR}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

os_mirror_enabled() {
  mirror_mode_enabled || return 1
  case "${FLASHCLI_OS_MIRROR:-1}" in
    0|false|no|off) return 1 ;;
    *) return 0 ;;
  esac
}

get_pip_bootstrap_url() {
  if [ -n "${GET_PIP_URL_OVERRIDE:-}" ]; then
    printf '%s\n' "$GET_PIP_URL_OVERRIDE"
    return 0
  fi
  # --pip-mirror pypi keeps official get-pip even under --mirror.
  case "${MIRROR_PIP_LABEL:-}" in
    pypi)
      printf '%s\n' "$GET_PIP_URL"
      return 0
      ;;
  esac
  if [ -n "${PIP_MIRROR_CHOICE:-}" ]; then
    case "$(normalize_pypi_mirror_label "$PIP_MIRROR_CHOICE" 2>/dev/null || true)" in
      pypi)
        printf '%s\n' "$GET_PIP_URL"
        return 0
        ;;
    esac
  fi
  if mirror_mode_enabled || [ -n "${PIP_MIRROR_CHOICE:-}" ]; then
    printf '%s\n' "$MIRROR_GET_PIP_URL"
    return 0
  fi
  printf '%s\n' "$GET_PIP_URL"
}

# Best-effort rewrite of OS package sources to Aliyun (root, Linux). Idempotent.
_apt_backup_sources_once() {
  if [ -f /etc/apt/sources.list ] && [ ! -f /etc/apt/sources.list.flashcli-bak ]; then
    cp -a /etc/apt/sources.list /etc/apt/sources.list.flashcli-bak 2>/dev/null || true
  fi
}

_apt_rewrite_mirror_urls_in_file() {
  _f="$1"
  [ -f "$_f" ] || return 0
  sed -i \
    -e 's|https\?://archive\.ubuntu\.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' \
    -e 's|https\?://security\.ubuntu\.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' \
    -e 's|https\?://ports\.ubuntu\.com/ubuntu-ports/|https://mirrors.aliyun.com/ubuntu-ports/|g' \
    -e 's|https\?://archive\.ubuntu\.com/ubuntu|https://mirrors.aliyun.com/ubuntu|g' \
    -e 's|https\?://security\.ubuntu\.com/ubuntu|https://mirrors.aliyun.com/ubuntu|g' \
    -e 's|https\?://deb\.debian\.org/debian/|https://mirrors.aliyun.com/debian/|g' \
    -e 's|https\?://security\.debian\.org/debian-security/|https://mirrors.aliyun.com/debian-security/|g' \
    -e 's|https\?://deb\.debian\.org/debian|https://mirrors.aliyun.com/debian|g' \
    -e 's|https\?://security\.debian\.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
    "$_f" 2>/dev/null || true
}

apply_apt_mirror() {
  have_cmd apt-get || return 0
  have_cmd sed || return 0
  _apt_backup_sources_once
  if ! grep -rq 'mirrors.aliyun.com' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    info "[i] mirror: switching apt sources → mirrors.aliyun.com (backup: sources.list.flashcli-bak)"
  else
    info "[i] mirror: normalizing apt sources to mirrors.aliyun.com (incl. *.sources)"
  fi
  for _f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    _apt_rewrite_mirror_urls_in_file "$_f"
  done
}

apt_os_packages_skip() {
  case "${FLASHCLI_SKIP_APT_OS_PACKAGES:-0}" in
    1 | true | yes) return 0 ;;
    *) return 1 ;;
  esac
}

warn_apt_gpg_repair() {
  warn "apt repository metadata failed (often GPG signature / stale lists on Ubuntu)."
  warn "  flashcli install can continue without OS packages (zip/git optional)."
  warn "  To repair the host, try:"
  warn "    rm -rf /var/lib/apt/lists/* && apt-get clean && apt-get update"
  warn "  Or set FLASHCLI_SKIP_APT_OS_PACKAGES=1 to silence OS package attempts."
}

apt_get_update_safe() {
  _log="${TMPDIR:-/tmp}/flashcli-apt-update-$$.log"
  if apt-get update -qq >"$_log" 2>&1; then
    rm -f "$_log" 2>/dev/null || true
    return 0
  fi
  if grep -qiE 'GPG error|not signed|invalid signature|EXPKEYSIG|NO_PUBKEY' "$_log" 2>/dev/null; then
    warn "apt update failed (GPG/signature) — clearing lists and retrying once ..."
    rm -rf /var/lib/apt/lists/* 2>/dev/null || true
    mkdir -p /var/lib/apt/lists/partial 2>/dev/null || true
    apt-get clean -qq 2>/dev/null || apt-get clean 2>/dev/null || true
    apply_apt_mirror
    if apt-get update -qq >"$_log" 2>&1; then
      rm -f "$_log" 2>/dev/null || true
      return 0
    fi
  fi
  if [ "$QUIET" != "1" ] && [ -f "$_log" ]; then
    tail -n 6 "$_log" >&2 || true
  fi
  rm -f "$_log" 2>/dev/null || true
  warn_apt_gpg_repair
  return 1
}

apply_dnf_yum_mirror() {
  _repos="/etc/yum.repos.d"
  [ -d "$_repos" ] || return 0
  have_cmd sed || return 0
  if grep -rq 'mirrors.aliyun.com' "$_repos" 2>/dev/null; then
    return 0
  fi
  info "[i] mirror: switching yum/dnf repos → mirrors.aliyun.com"
  for f in "$_repos"/*.repo; do
    [ -f "$f" ] || continue
    sed -i \
      -e 's|^mirrorlist=|#mirrorlist=|g' \
      -e 's|^#baseurl=|baseurl=|g' \
      -e 's|http://mirror.centos.org|https://mirrors.aliyun.com|g' \
      -e 's|https://mirror.centos.org|https://mirrors.aliyun.com|g' \
      -e 's|http://vault.centos.org|https://mirrors.aliyun.com|g' \
      -e 's|https://vault.centos.org|https://mirrors.aliyun.com|g' \
      -e 's|http://mirrorlist.centos.org|https://mirrors.aliyun.com|g' \
      -e 's|https://mirrors.fedoraproject.org|https://mirrors.aliyun.com/fedora|g' \
      -e 's|http://download.fedoraproject.org|https://mirrors.aliyun.com/fedora|g' \
      -e 's|https://download.fedoraproject.org|https://mirrors.aliyun.com/fedora|g' \
      "$f" 2>/dev/null || true
  done
}

apply_apk_mirror() {
  _f="/etc/apk/repositories"
  [ -f "$_f" ] || return 0
  have_cmd sed || return 0
  if grep -q 'mirrors.aliyun.com' "$_f" 2>/dev/null; then
    return 0
  fi
  info "[i] mirror: switching apk repositories → mirrors.aliyun.com"
  if [ ! -f "${_f}.flashcli-bak" ]; then
    cp -a "$_f" "${_f}.flashcli-bak" 2>/dev/null || true
  fi
  sed -i \
    -e 's|https\?://dl-cdn.alpinelinux.org|https://mirrors.aliyun.com|g' \
    "$_f" 2>/dev/null || true
}

apply_zypper_mirror() {
  _dir="/etc/zypp/repos.d"
  [ -d "$_dir" ] || return 0
  have_cmd sed || return 0
  if grep -rq 'mirrors.aliyun.com' "$_dir" 2>/dev/null; then
    return 0
  fi
  info "[i] mirror: switching zypper repos → mirrors.aliyun.com"
  for f in "$_dir"/*.repo; do
    [ -f "$f" ] || continue
    sed -i \
      -e 's|http://download.opensuse.org|https://mirrors.aliyun.com/opensuse|g' \
      -e 's|https://download.opensuse.org|https://mirrors.aliyun.com/opensuse|g' \
      "$f" 2>/dev/null || true
  done
}

apply_os_package_mirrors() {
  os_mirror_enabled || return 0
  [ "$OS_MIRRORS_APPLIED" -eq 1 ] && return 0
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    warn "mirror: OS package sources need root — skipping apt/yum/dnf/apk rewrite (pip/HF mirrors still active)"
    return 0
  fi
  apply_apt_mirror
  apply_dnf_yum_mirror
  apply_apk_mirror
  apply_zypper_mirror
  OS_MIRRORS_APPLIED=1
}

pypi_mirror_probe_enabled() {
  mirror_mode_enabled || return 1
  [ -n "${PIP_MIRROR_CHOICE:-}" ] && return 1
  case "${PIP_MIRROR_PROBE}" in
    0|false|no|off) return 1 ;;
    *) return 0 ;;
  esac
}

normalize_pypi_mirror_label() {
  _raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$_raw" in
    tuna|tsinghua|qinghua|清华) printf '%s\n' "tuna" ;;
    aliyun|阿里) printf '%s\n' "aliyun" ;;
    tencent|腾讯) printf '%s\n' "tencent" ;;
    ustc|中科大) printf '%s\n' "ustc" ;;
    huawei|华为) printf '%s\n' "huawei" ;;
    pypi|official|global|upstream|官方) printf '%s\n' "pypi" ;;
    *) return 1 ;;
  esac
}

apply_pypi_mirror_label() {
  _label="$(normalize_pypi_mirror_label "$1")" || return 1
  MIRROR_PIP_LABEL="$_label"
  case "$_label" in
    tuna)
      MIRROR_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple/"
      MIRROR_PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn"
      ;;
    aliyun)
      MIRROR_PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
      MIRROR_PIP_TRUSTED_HOST="mirrors.aliyun.com"
      ;;
    tencent)
      MIRROR_PIP_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple/"
      MIRROR_PIP_TRUSTED_HOST="mirrors.cloud.tencent.com"
      ;;
    ustc)
      MIRROR_PIP_INDEX_URL="https://mirrors.ustc.edu.cn/pypi/web/simple/"
      MIRROR_PIP_TRUSTED_HOST="mirrors.ustc.edu.cn"
      ;;
    huawei)
      MIRROR_PIP_INDEX_URL="https://mirrors.huaweicloud.com/repository/pypi/simple/"
      MIRROR_PIP_TRUSTED_HOST="mirrors.huaweicloud.com"
      ;;
    pypi)
      MIRROR_PIP_INDEX_URL="https://pypi.org/simple/"
      MIRROR_PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"
      ;;
    *) return 1 ;;
  esac
  return 0
}

# Map PEP 503 simple index URL → packages/ base (fallback when python3 is unavailable).
pypi_packages_base_from_index() {
  _index="$1"
  case "$_index" in
    */web/simple/)
      printf '%s\n' "${_index%web/simple/}packages/"
      return 0
      ;;
    */simple/)
      printf '%s\n' "${_index%simple/}packages/"
      return 0
      ;;
  esac
  return 1
}

# Resolve a PEP 503 wheel href from {index}{package}/ into a fetchable URL.
pypi_pep503_probe_wheel_url() {
  _index="$1"
  _package="${2:-$PYPI_PROBE_PACKAGE}"
  _page="${_index}${_package}/"
  _html="$(curl -fsSL --connect-timeout 3 --max-time "$PYPI_MIRROR_PROBE_TIMEOUT" \
    "$_page" 2>/dev/null)" || return 1
  _href="$(printf '%s' "$_html" | sed -n 's/.*href="\([^"]*\.whl\)[#"].*/\1/p' \
    | grep -E '(none-any|manylinux.*x86_64)\.whl$' | tail -n 1)"
  [ -n "$_href" ] || _href="$(printf '%s' "$_html" | sed -n 's/.*href="\([^"]*\.whl\)[#"].*/\1/p' \
    | grep 'none-any\.whl$' | tail -n 1)"
  [ -n "$_href" ] || _href="$(printf '%s' "$_html" | sed -n 's/.*href="\([^"]*\.whl\)[#"].*/\1/p' | tail -n 1)"
  [ -n "$_href" ] || return 1
  if have_cmd python3; then
    python3 - "$_page" "$_href" <<'PY'
import sys
from urllib.parse import urljoin
print(urljoin(sys.argv[1], sys.argv[2]))
PY
    return 0
  fi
  case "$_href" in
    http://*|https://*)
      printf '%s\n' "${_href%%#*}"
      return 0
      ;;
    ../../packages/*)
      _root="${_index}"
      while case "$_root" in */) true;; *) false;; esac; do _root="${_root%/}"; done
      _root="${_root%%/simple*}"
      _root="${_root%%/web*}"
      printf '%s/%s\n' "${_root%/}" "${_href#../../}"
      return 0
      ;;
  esac
  return 1
}

# Download a fixed-size sample (HTTP Range when supported); print "seconds|bytes".
_http_probe_sample_result() {
  _url="$1"
  _sample_bytes="${2:-$PYPI_MIRROR_PROBE_SAMPLE_BYTES}"
  _min_bytes="${3:-$PYPI_MIRROR_PROBE_MIN_BYTES}"
  _range_end=$((_sample_bytes - 1))
  if have_cmd curl; then
    _raw="$(curl -fsSL --connect-timeout 5 --max-time "$PYPI_MIRROR_PROBE_TIMEOUT" \
      -r "0-${_range_end}" \
      -o /dev/null -w '%{time_total}\n%{size_download}' "$_url" 2>/dev/null)" || return 1
    _time="${_raw%%$'\n'*}"
    _bytes="${_raw#*$'\n'}"
    [ -n "$_time" ] && [ -n "$_bytes" ] || return 1
    _bytes_int="${_bytes%%.*}"
    [ "${_bytes_int:-0}" -ge "$_min_bytes" ] 2>/dev/null || return 1
    printf '%s|%s\n' "$_time" "$_bytes_int"
    return 0
  fi
  if have_cmd wget; then
    _tmp="$(mktemp "${TMPDIR:-/tmp}/flashcli-pypi-probe.XXXXXX" 2>/dev/null || echo "/tmp/flashcli-pypi-probe-$$")"
    _start="$(date +%s 2>/dev/null || echo 0)"
    wget -q --timeout="$PYPI_MIRROR_PROBE_TIMEOUT" -O "$_tmp" "$_url" 2>/dev/null || {
      rm -f "$_tmp" 2>/dev/null || true
      return 1
    }
    _end="$(date +%s 2>/dev/null || echo 0)"
    _bytes_int="$(wc -c < "$_tmp" 2>/dev/null | tr -d ' ')"
    rm -f "$_tmp" 2>/dev/null || true
    [ "${_bytes_int:-0}" -ge "$_min_bytes" ] 2>/dev/null || return 1
    printf '%s|%s\n' "$((_end - _start))" "$_bytes_int"
    return 0
  fi
  return 1
}

_probe_pypi_candidate() {
  _label="$1"
  _index="$2"
  _host="$3"
  _priority="$4"
  _out="$5"
  _probe_url="$(pypi_pep503_probe_wheel_url "$_index")" || return 0
  _sample="$(_http_probe_sample_result "$_probe_url")" || return 0
  _t="${_sample%%|*}"
  _bytes="${_sample#*|}"
  [ -n "$_t" ] && [ -n "$_bytes" ] || return 0
  printf '%s|%s|%s|%s|%s|%s\n' "$_t" "$_priority" "$_label" "$_index" "$_host" "$_bytes" > "$_out"
}

# Parallel probe of common China PyPI mirrors; pick highest throughput (tie-break: priority).
probe_fastest_pypi_mirror() {
  have_cmd curl || have_cmd wget || return 0

  _tmpdir="${TMPDIR:-/tmp}/flashcli-pypi-probe-$$"
  mkdir -p "$_tmpdir" || return 0
  _jobs=0

  for _entry in \
    "tuna|https://pypi.tuna.tsinghua.edu.cn/simple/|pypi.tuna.tsinghua.edu.cn|1" \
    "tencent|https://mirrors.cloud.tencent.com/pypi/simple/|mirrors.cloud.tencent.com|2" \
    "ustc|https://mirrors.ustc.edu.cn/pypi/web/simple/|mirrors.ustc.edu.cn|3" \
    "aliyun|https://mirrors.aliyun.com/pypi/simple/|mirrors.aliyun.com|4" \
    "huawei|https://mirrors.huaweicloud.com/repository/pypi/simple/|mirrors.huaweicloud.com|5"
  do
    _label="${_entry%%|*}"
    _rest="${_entry#*|}"
    _index="${_rest%%|*}"
    _rest="${_rest#*|}"
    _host="${_rest%%|*}"
    _priority="${_rest#*|}"
    _probe_pypi_candidate "$_label" "$_index" "$_host" "$_priority" "${_tmpdir}/${_label}" &
    _jobs=$((_jobs + 1))
  done
  wait

  _best=""
  if [ "$_jobs" -gt 0 ]; then
    _best="$(cat "$_tmpdir"/* 2>/dev/null | sort -t'|' -k1,1n -k2,2n | head -n 1 || true)"
  fi
  rm -rf "$_tmpdir" 2>/dev/null || true

  if [ -z "$_best" ]; then
    warn "mirror: PyPI probe found no reachable mirror — using Tsinghua default"
    apply_pypi_mirror_label "tuna" || true
    return 0
  fi

  _t="${_best%%|*}"
  _rest="${_best#*|}"
  _priority="${_rest%%|*}"
  _rest="${_rest#*|}"
  MIRROR_PIP_LABEL="${_rest%%|*}"
  _rest="${_rest#*|}"
  MIRROR_PIP_INDEX_URL="${_rest%%|*}"
  _rest="${_rest#*|}"
  MIRROR_PIP_TRUSTED_HOST="${_rest%%|*}"
  _bytes="${_rest#*|}"
  _mbps=""
  if have_cmd awk && [ -n "$_t" ] && [ -n "$_bytes" ]; then
    _mbps="$(awk "BEGIN {printf \"%.1f\", ${_bytes} / ${_t} / 1048576}")"
  fi
  if [ -n "$_mbps" ]; then
    info "[i] mirror: PyPI throughput probe → ${MIRROR_PIP_LABEL} (~${_mbps} MiB/s, ${MIRROR_PIP_INDEX_URL})"
  else
    info "[i] mirror: PyPI throughput probe → ${MIRROR_PIP_LABEL} (${_t}s, ${MIRROR_PIP_INDEX_URL})"
  fi
}

configure_pypi_mirror() {
  [ -n "${PIP_INDEX_URL:-}" ] && return 0

  if [ -n "${PIP_MIRROR_CHOICE:-}" ]; then
    apply_pypi_mirror_label "$PIP_MIRROR_CHOICE" \
      || die "unknown PyPI mirror: $PIP_MIRROR_CHOICE (try: tuna, aliyun, tencent, ustc, huawei, pypi)"
    info "[i] pip: using mirror ${MIRROR_PIP_LABEL} (${MIRROR_PIP_INDEX_URL})"
    return 0
  fi

  if pypi_mirror_probe_enabled; then
    probe_fastest_pypi_mirror
    return 0
  fi

  apply_pypi_mirror_label "tuna" || true
  info "[i] pip: default mirror ${MIRROR_PIP_LABEL} (${MIRROR_PIP_INDEX_URL}) — use --pip-probe to benchmark or --pip-mirror to pin"
}

# Auto PyPI failover: --mirror, no --pip-mirror / FLASHCLI_PIP_MIRROR, no user PIP_INDEX_URL.
pypi_auto_failover_enabled() {
  mirror_mode_enabled || return 1
  [ -n "${PIP_MIRROR_CHOICE:-}" ] && return 1
  [ "${PIP_INDEX_URL_USER_SET:-0}" = "1" ] && return 1
  case "${FLASHCLI_PIP_FAILOVER:-1}" in
    0|false|no|off) return 1 ;;
  esac
  return 0
}

# Ordered China mirrors used when unpinned --mirror hits network/index errors.
pypi_failover_labels() {
  printf '%s\n' tuna aliyun ustc tencent huawei
}

# Labels after $_from in the failover chain (does not include $_from).
pypi_failover_labels_after() {
  _from="${1:-tuna}"
  _pass=0
  for _lab in tuna aliyun ustc tencent huawei; do
    if [ "$_pass" -eq 0 ]; then
      if [ "$_lab" = "$_from" ]; then
        _pass=1
      fi
      continue
    fi
    printf '%s\n' "$_lab"
  done
}

switch_active_pypi_mirror() {
  apply_pypi_mirror_label "$1" || return 1
  export PIP_INDEX_URL="$MIRROR_PIP_INDEX_URL"
  export PIP_TRUSTED_HOST="$MIRROR_PIP_TRUSTED_HOST"
  info "[i] pip: switched index → ${MIRROR_PIP_LABEL} (${PIP_INDEX_URL})"
}

# True when pip log looks like index/network/sync issues (not resolver/build/perm errors).
pip_log_is_pypi_failover_candidate() {
  _f="${1:-}"
  [ -n "$_f" ] && [ -f "$_f" ] || return 1
  if grep -qiE \
    'ResolutionImpossible|conflicting dependencies|Cannot uninstall|externally-managed-environment|Permission denied|Disk quota|No space left|Invalid requirement|metadata-generation-failed|Failed building wheel|error: command .* failed|Microsoft Visual C\+\+|Could not build wheels' \
    "$_f" 2>/dev/null; then
    return 1
  fi
  grep -qiE \
    'HTTP Error 40[0345]|403 Forbidden|404 Client Error|404 Not Found|Could not fetch URL|Connection refused|Connection reset|Connection timed out|Read timed out|timed out\.|Max retries exceeded|Failed to establish|Name or service not known|Temporary failure in name resolution|Network is unreachable|SSLError|SSLEOFError|urlopen error|ProxyError|Remote end closed|IncompleteRead|No matching distribution found|Could not find a version that satisfies' \
    "$_f" 2>/dev/null
}

# Apply mirror endpoints unless the user already exported overrides.
apply_mirror_endpoints() {
  if mirror_mode_enabled || [ -n "${PIP_MIRROR_CHOICE:-}" ]; then
    configure_pypi_mirror

    if [ -z "${PIP_INDEX_URL:-}" ]; then
      export PIP_INDEX_URL="$MIRROR_PIP_INDEX_URL"
      export PIP_TRUSTED_HOST="$MIRROR_PIP_TRUSTED_HOST"
    fi
    if [ -z "${PIP_DEFAULT_TIMEOUT:-}" ]; then
      export PIP_DEFAULT_TIMEOUT=120
    fi

    info "[i] pip: PIP_INDEX_URL=${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
    if [ -n "${PIP_MIRROR_CHOICE:-}" ] && ! mirror_mode_enabled; then
      info "[i] pip mirror only (add --mirror for HF/git/OS mirrors)"
      return 0
    fi
  fi

  mirror_mode_enabled || return 0

  if [ -z "${HF_ENDPOINT:-}" ]; then
    export HF_ENDPOINT="$MIRROR_HF_ENDPOINT"
  fi
  if [ -z "${FLASHCLI_PREFER_HF_MIRROR:-}" ]; then
    export FLASHCLI_PREFER_HF_MIRROR=1
  fi
  if [ -z "${FLASHCLI_GIT_PROXY:-}" ]; then
    export FLASHCLI_GIT_PROXY="$DEFAULT_GIT_PROXY_PREFIX"
  fi

  maybe_apply_default_git_proxy
  apply_os_package_mirrors

  info "[i] mirror: HF_ENDPOINT=${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
  info "[i] mirror: FLASHCLI_GIT_PROXY=${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}"
  info "[i] mirror: get-pip → $(get_pip_bootstrap_url)"
}

# When --mirror is on: prefer Gitee first for the official repo (fallback order is in
# ensure_git_remote_ready). Other GitHub URLs get FLASHCLI_GIT_PROXY if set.
maybe_apply_default_git_proxy() {
  mirror_mode_enabled || return 0
  [ "$REPO_FROM_USER" -eq 1 ] && return 0

  if [ "$REPO" = "$DEFAULT_REPO_GITHUB" ]; then
    REPO="$DEFAULT_REPO_GITEE"
    info "[i] mirror: git order Gitee → GitHub → GitHub proxy (${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}); pass --github to prefer GitHub first"
    return 0
  fi

  case "${FLASHCLI_GIT_PROXY:-}" in
    ""|auto|0|false|no|off) return 0 ;;
  esac
  case "$REPO" in
    https://github.com/*) ;;
    *) return 0 ;;
  esac
  _proxy="${FLASHCLI_GIT_PROXY}"
  _proxy="${_proxy%/}/"
  REPO="${_proxy}${REPO}"
  info "[i] mirror: git fetch via ${REPO}"
}

# Keep git non-interactive for this process tree (preflight + pip git+ + tests).
#
# Keep this MINIMAL. Sending blank username/password or a custom askpass makes the
# client look like an auth attempt; Gitee risk-control often answers with
# `reject by [gitee]` / Authentication failed — including in containers that used to
# succeed with plain anonymous HTTPS. Only disable prompts and ignore stored helpers.
configure_noninteractive_git() {
  export GIT_TERMINAL_PROMPT=0
  export GCM_INTERACTIVE=never
  unset GIT_ASKPASS SSH_ASKPASS SSH_ASKPASS_REQUIRE GIT_ASKPASS_REQUIRE 2>/dev/null || true

  _n="${GIT_CONFIG_COUNT:-0}"
  case "$_n" in ''|*[!0-9]*) _n=0 ;; esac
  # Empty helper: do not use store/cache/osxkeychain (stale creds) and do not send auth.
  export "GIT_CONFIG_KEY_${_n}=credential.helper"
  export "GIT_CONFIG_VALUE_${_n}="
  _n=$((_n + 1))
  export "GIT_CONFIG_KEY_${_n}=credential.interactive"
  export "GIT_CONFIG_VALUE_${_n}=never"
  _n=$((_n + 1))
  export GIT_CONFIG_COUNT="$_n"
}

# HTTP status for git-upload-pack advertisement (anonymous). Helps explain 401 vs network.
probe_git_upload_pack_http() {
  _repo="$1"
  case "$_repo" in
    https://*|http://*) ;;
    *) printf '%s\n' "n/a"; return 0 ;;
  esac
  _base="${_repo%.git}"
  _url="${_base}.git/info/refs?service=git-upload-pack"
  if have_cmd curl; then
    curl -sS -o /dev/null -w '%{http_code}' \
      --connect-timeout 8 --max-time 20 \
      "$_url" 2>/dev/null || printf '%s\n' "000"
    return 0
  fi
  printf '%s\n' "n/a"
}

# Run git with a network timeout so preflight cannot hang silently on dead proxies.
# Pure anonymous: empty credential.helper (no Authorization header).
run_git_timeout() {
  _secs="${FLASHCLI_GIT_TIMEOUT:-25}"
  if have_cmd timeout; then
    GIT_TERMINAL_PROMPT=0 timeout "$_secs" git -c credential.helper= \
      -c credential.interactive=never "$@"
    return $?
  fi
  GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.interactive=never \
    -c http.lowSpeedLimit=1000 -c "http.lowSpeedTime=${_secs}" "$@"
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help)
        usage
        exit 0
        ;;
      -q|--quiet)
        QUIET=1
        shift
        ;;
      --ref|--branch)
        [ $# -ge 2 ] || die "$1 requires a value"
        REF="$2"
        shift 2
        ;;
      --repo|--git-url)
        [ $# -ge 2 ] || die "$1 requires a value"
        REPO="$2"
        REPO_FROM_USER=1
        shift 2
        ;;
      --mirror)
        USE_MIRROR=1
        shift
        ;;
      --pip-probe)
        PIP_MIRROR_PROBE=1
        shift
        ;;
      --pip-mirror|--pypi-mirror)
        [ $# -ge 2 ] || die "$1 requires a mirror name (tuna|aliyun|tencent|ustc|huawei|pypi)"
        PIP_MIRROR_CHOICE="$2"
        shift 2
        ;;
      --global|--no-mirror)
        USE_MIRROR=0
        shift
        ;;
      --gitee)
        REPO="$DEFAULT_REPO_GITEE"
        REPO_FROM_USER=1
        shift
        ;;
      --github)
        REPO="$DEFAULT_REPO_GITHUB"
        REPO_FROM_USER=1
        shift
        ;;
      --run-tests)
        RUN_TESTS=1
        shift
        ;;
      --run-core-tests)
        RUN_CORE_TESTS=1
        shift
        ;;
      --)
        shift
        break
        ;;
      -*)
        die "unknown option: $1 (try --help)"
        ;;
      *)
        die "unexpected argument: $1 (try --help)"
        ;;
    esac
  done
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# venv lives under HOME; containers sometimes omit it.
ensure_home() {
  if [ -n "${HOME:-}" ] && [ -d "${HOME:-}" ]; then
    return 0
  fi
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
    export HOME=/root
    info "[i] HOME unset — using /root"
    return 0
  fi
  _u="$(id -un 2>/dev/null || echo "")"
  if [ -n "$_u" ] && have_cmd getent; then
    _home="$(getent passwd "$_u" 2>/dev/null | cut -d: -f6 || true)"
    if [ -n "$_home" ] && [ -d "$_home" ]; then
      export HOME="$_home"
      info "[i] HOME unset — using $_home"
      return 0
    fi
  fi
  die "HOME is not set and could not be determined — required for ~/.flashcli/venv (set HOME=... or re-run as root)"
}

ensure_download_tool() {
  have_cmd curl && return 0
  have_cmd wget && return 0
  warn "curl/wget not found — attempting OS package install ..."
  install_os_packages curl \
    || install_os_packages wget \
    || die "curl or wget required to bootstrap pip (get-pip.py) — install curl and re-run"
}

path_has_dir() {
  case ":${PATH:-}:" in *":$1:"*) return 0 ;; esac
  return 1
}

# True if executable is Python >= REQUIRES_PYTHON_MIN.
python_usable() {
  _py="$1"
  [ -n "$_py" ] || return 1
  if [ -x "$_py" ]; then
    :
  elif have_cmd "$_py"; then
    _py="$(command -v "$_py")"
  else
    return 1
  fi
  "$_py" -c "
import sys
need = tuple(int(x) for x in '${REQUIRES_PYTHON_MIN}'.split('.'))
raise SystemExit(0 if sys.version_info >= need else 1)
" 2>/dev/null
}

python_version_line() {
  "$1" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown
}

resolve_python_path() {
  _cmd="$1"
  if [ -x "$_cmd" ]; then
    printf '%s' "$_cmd"
    return 0
  fi
  if have_cmd "$_cmd"; then
    command -v "$_cmd"
    return 0
  fi
  return 1
}

python_has_pip() {
  _py="$1"
  "$_py" -m pip --version >/dev/null 2>&1
}

python_is_pep668() {
  _py="$1"
  "$_py" -c "
import os, sysconfig
stdlib = sysconfig.get_path('stdlib')
raise SystemExit(0 if os.path.isfile(os.path.join(stdlib, 'EXTERNALLY-MANAGED')) else 1)
" 2>/dev/null
}

# Prefer interpreters that already have pip (e.g. /usr/local python3.12 over Debian python3.13).
discover_python() {
  _best_pip=""
  _best_pip_maj=0
  _best_pip_min=0
  _best_no=""
  _best_no_maj=0
  _best_no_min=0
  _seen=""

  if [ -n "${FLASHCLI_PYTHON:-}" ]; then
    if python_usable "${FLASHCLI_PYTHON}"; then
      printf '%s' "$(resolve_python_path "${FLASHCLI_PYTHON}")"
      return 0
    fi
    die "FLASHCLI_PYTHON=${FLASHCLI_PYTHON} is not Python >= ${REQUIRES_PYTHON_MIN}"
  fi

  for cmd in $PYTHON_CANDIDATES; do
    [ -n "$cmd" ] || continue
    _path="$(resolve_python_path "$cmd" 2>/dev/null || true)"
    [ -n "$_path" ] || continue
    case "$_seen" in *"|${_path}|"*) continue ;; esac
    _seen="${_seen}|${_path}|"
    python_usable "$_path" || continue

    maj_min="$("$_path" -c 'import sys; print(f"{sys.version_info[0]} {sys.version_info[1]}")' 2>/dev/null)" || continue
    maj="${maj_min%% *}"
    min="${maj_min#* }"

    if python_has_pip "$_path"; then
      if [ "$maj" -gt "$_best_pip_maj" ] || { [ "$maj" -eq "$_best_pip_maj" ] && [ "$min" -gt "$_best_pip_min" ]; }; then
        _best_pip_maj="$maj"
        _best_pip_min="$min"
        _best_pip="$_path"
      fi
    else
      if [ "$maj" -gt "$_best_no_maj" ] || { [ "$maj" -eq "$_best_no_maj" ] && [ "$min" -gt "$_best_no_min" ]; }; then
        _best_no_maj="$maj"
        _best_no_min="$min"
        _best_no="$_path"
      fi
    fi
  done

  if [ -n "$_best_pip" ]; then
    printf '%s' "$_best_pip"
    return 0
  fi
  if [ -n "$_best_no" ]; then
    printf '%s' "$_best_no"
    return 0
  fi
  return 1
}

should_break_system_packages() {
  case "${FLASHCLI_BREAK_SYSTEM_PACKAGES:-auto}" in
    0 | false | no) return 1 ;;
    1 | true | yes) return 0 ;;
  esac
  # auto: only for PEP 668 system installs (Debian/Ubuntu + /usr/bin/python3.x)
  if [ "${PIP_INSTALL_USER:-0}" = "1" ]; then
    return 1
  fi
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    return 1
  fi
  python_is_pep668 "$PYTHON" 2>/dev/null
}

# True if `python -m pip install --help` lists the given long option (e.g. root-user-action).
pip_has_option() {
  _opt="$1"
  [ -n "$_opt" ] || return 1
  run_py -m pip install --help 2>/dev/null | grep -q -- "--${_opt}"
}

pip_extra_flags() {
  # Only for system (non-venv) PEP 668 installs; requires pip>=23.0.1.
  if should_break_system_packages && pip_has_option break-system-packages; then
    printf '%s' '--break-system-packages'
  fi
}

die_no_python() {
  _reason="unknown"
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    _reason="running as non-root — cannot auto-install OS python packages"
  elif ! auto_install_python_enabled; then
    _reason="FLASHCLI_AUTO_INSTALL_PYTHON=0 disabled automatic python install"
  elif ! have_cmd apt-get && ! have_cmd dnf && ! have_cmd yum && ! have_cmd apk && ! have_cmd zypper; then
    _reason="no supported package manager (need apt, dnf, yum, apk, or zypper)"
  else
    _reason="OS package install for python3 failed (network, repos, or disk)"
  fi
  printf '%s\n' "error: cannot install flashcli — no Python >= ${REQUIRES_PYTHON_MIN} available." >&2
  printf '%s\n' "error: reason: ${_reason}" >&2
  printf '%s\n' "error: searched: ${PYTHON_CANDIDATES:-python3}" >&2
  printf '%s\n' "error:" >&2
  printf '%s\n' "error: Fix options:" >&2
  printf '%s\n' "error:   1. Re-run as root (auto-installs python3+pip+git by default)" >&2
  printf '%s\n' "error:   2. Install Python 3.10+ manually, then re-run:" >&2
  printf '%s\n' "error:        Debian/Ubuntu: apt install -y python3 python3-pip python3-venv git" >&2
  printf '%s\n' "error:        RHEL/Fedora:   dnf install -y python3 python3-pip git" >&2
  printf '%s\n' "error:        Alpine:        apk add python3 py3-pip git" >&2
  printf '%s\n' "error:   3. Point to an existing interpreter: FLASHCLI_PYTHON=/usr/bin/python3.12 ./install.sh" >&2
  exit 1
}

auto_install_python_enabled() {
  case "${FLASHCLI_AUTO_INSTALL_PYTHON:-1}" in
    0 | false | no | off) return 1 ;;
    *) return 0 ;;
  esac
}

should_use_venv() {
  case "${FLASHCLI_USE_VENV:-1}" in
    0 | false | no | off) return 1 ;;
    *) return 0 ;;
  esac
}

flashcli_home_path() {
  printf '%s' "${FLASHCLI_HOME:-${HOME:-/root}/.flashcli}"
}

flashcli_venv_path() {
  # Prefer FLASHCLI_VENV; else $FLASHCLI_HOME/venv (same root as mirror.env / install.env).
  if [ -n "${FLASHCLI_VENV:-}" ]; then
    printf '%s' "$FLASHCLI_VENV"
    return 0
  fi
  printf '%s' "$(flashcli_home_path)/venv"
}

try_auto_install_python() {
  if ! auto_install_python_enabled; then
    return 1
  fi
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    warn "auto python install requires root; skipping OS package install"
    return 1
  fi
  info "Attempting OS package install for python3 + pip + git + zip + rsync ..."
  apply_os_package_mirrors
  if [ "$APT_OS_PACKAGES_DISABLED" -eq 1 ] || apt_os_packages_skip; then
    warn "Skipping OS python install (apt disabled or FLASHCLI_SKIP_APT_OS_PACKAGES=1)"
    return 1
  fi
  if have_cmd apt-get; then
    if apt_get_update_safe && apt-get install -y python3 python3-pip python3-venv git zip rsync; then
      return 0
    fi
    APT_OS_PACKAGES_DISABLED=1
    return 1
  fi
  if have_cmd dnf; then
    dnf install -y python3 python3-pip python3-virtualenv git zip rsync 2>/dev/null \
      || dnf install -y python3 python3-pip git zip rsync && return 0
  fi
  if have_cmd yum; then
    yum install -y python3 python3-pip python3-virtualenv git zip rsync 2>/dev/null \
      || yum install -y python3 python3-pip git zip rsync && return 0
  fi
  if have_cmd apk; then
    apk add --no-cache python3 py3-pip py3-virtualenv git zip rsync 2>/dev/null \
      || apk add --no-cache python3 py3-pip git zip rsync && return 0
  fi
  if have_cmd zypper; then
    zypper --non-interactive install python3 python3-pip git zip rsync && return 0
  fi
  return 1
}

resolve_python() {
  if PYTHON="$(discover_python)"; then
    export PYTHON FLASHCLI_BASE_PYTHON="$PYTHON"
    return 0
  fi
  if try_auto_install_python; then
    PYTHON="$(discover_python)" && export PYTHON FLASHCLI_BASE_PYTHON="$PYTHON" && return 0
  fi
  die_no_python
}

# Run Python (honours PYTHONNOUSERSITE when set).
run_py() {
  "$PYTHON" "$@"
}

# pip install once (PEP 668 / old pip fallbacks). On failure keeps FLASHCLI_LAST_PIP_LOG.
_do_pip_install_once() {
  _log="/tmp/flashcli-pip-$$.log"
  FLASHCLI_LAST_PIP_LOG=""
  _break="$(pip_extra_flags || true)"
  # --root-user-action only silences a warning on *system* root installs (pip>=22.1).
  # Never pass it inside a venv — unnecessary, and breaks Ubuntu 22.04's pip 22.0.x.
  if [ -z "${VIRTUAL_ENV:-}" ] && [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
    if pip_has_option root-user-action; then
      set -- --root-user-action=ignore "$@"
    fi
  fi
  _run_pip() {
    if run_py -m pip install "$@" >"$_log" 2>&1; then
      [ "$QUIET" = "1" ] || cat "$_log" >&2
      return 0
    fi
    [ "$QUIET" = "1" ] || cat "$_log" >&2
    return 1
  }
  if [ -n "$_break" ]; then
    if _run_pip $_break "$@"; then
      rm -f "$_log"
      return 0
    fi
  elif _run_pip "$@"; then
    rm -f "$_log"
    return 0
  fi
  if grep -qi 'externally-managed-environment' "$_log" 2>/dev/null; then
    if should_use_venv && [ -z "${VIRTUAL_ENV:-}" ]; then
      warn "PEP 668 externally-managed environment — switching to venv and retrying pip ..."
      if ensure_flashcli_venv; then
        if _run_pip "$@"; then
          rm -f "$_log"
          return 0
        fi
      fi
    fi
    if should_break_system_packages && pip_has_option break-system-packages; then
      warn "PEP 668 — retrying pip with --break-system-packages"
      if run_py -m pip install --break-system-packages "$@" >"$_log" 2>&1; then
        [ "$QUIET" = "1" ] || cat "$_log" >&2
        rm -f "$_log"
        return 0
      fi
    fi
  fi
  FLASHCLI_LAST_PIP_LOG="$_log"
  cat "$_log" >&2
  return 1
}

# pip install with optional PyPI mirror failover (unpinned --mirror only).
do_pip_install() {
  if _do_pip_install_once "$@"; then
    return 0
  fi
  if ! pypi_auto_failover_enabled; then
    rm -f "${FLASHCLI_LAST_PIP_LOG:-}" 2>/dev/null || true
    FLASHCLI_LAST_PIP_LOG=""
    return 1
  fi
  if ! pip_log_is_pypi_failover_candidate "${FLASHCLI_LAST_PIP_LOG:-}"; then
    rm -f "${FLASHCLI_LAST_PIP_LOG:-}" 2>/dev/null || true
    FLASHCLI_LAST_PIP_LOG=""
    return 1
  fi

  _failed_label="${MIRROR_PIP_LABEL:-tuna}"
  _last_log="${FLASHCLI_LAST_PIP_LOG:-}"
  for _lab in $(pypi_failover_labels_after "$_failed_label"); do
    warn "pip via ${_failed_label} failed (network/index) — retrying with ${_lab} ..."
    rm -f "$_last_log" 2>/dev/null || true
    switch_active_pypi_mirror "$_lab" || continue
    if _do_pip_install_once "$@"; then
      info "[ok] pip install succeeded via ${_lab}"
      return 0
    fi
    if ! pip_log_is_pypi_failover_candidate "${FLASHCLI_LAST_PIP_LOG:-}"; then
      rm -f "${FLASHCLI_LAST_PIP_LOG:-}" 2>/dev/null || true
      FLASHCLI_LAST_PIP_LOG=""
      return 1
    fi
    _failed_label="$_lab"
    _last_log="${FLASHCLI_LAST_PIP_LOG:-}"
  done
  rm -f "${FLASHCLI_LAST_PIP_LOG:-}" 2>/dev/null || true
  FLASHCLI_LAST_PIP_LOG=""
  return 1
}

pip_works() {
  run_py -m pip --version >/dev/null 2>&1
}

pip_version_ok() {
  run_py - <<'PY' 2>/dev/null
import re, subprocess, sys

def parse_ver(s):
    parts = []
    for x in s.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            break
    return tuple(parts)

r = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True)
if r.returncode != 0:
    raise SystemExit(1)
m = re.search(r"pip\s+([\d.]+)", r.stdout or r.stderr or "")
if not m:
    raise SystemExit(1)
min_s = __import__("os").environ.get("FLASHCLI_MIN_PIP_VERSION", "21.3")
raise SystemExit(0 if parse_ver(m.group(1)) >= parse_ver(min_s) else 1)
PY
}

try_os_install_pip() {
  [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] || return 1
  if ! auto_install_python_enabled; then
    return 1
  fi
  apply_os_package_mirrors
  if have_cmd apt-get; then
    info "Installing python3-pip via apt (Debian/Ubuntu) ..."
    apt-get update -qq && apt-get install -y python3-pip python3-venv \
      && return 0
  fi
  if have_cmd dnf; then
    info "Installing python3-pip via dnf ..."
    dnf install -y python3-pip && return 0
  fi
  if have_cmd yum; then
    info "Installing python3-pip via yum ..."
    yum install -y python3-pip && return 0
  fi
  if have_cmd apk; then
    info "Installing py3-pip via apk ..."
    apk add --no-cache py3-pip && return 0
  fi
  if have_cmd zypper; then
    info "Installing python3-pip via zypper ..."
    zypper --non-interactive install python3-pip && return 0
  fi
  return 1
}

ensure_venv_module() {
  if run_py -m venv -h >/dev/null 2>&1; then
    return 0
  fi
  if ! auto_install_python_enabled; then
    return 1
  fi
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    return 1
  fi
  info "python venv module missing — installing python3-venv ..."
  apply_os_package_mirrors
  if have_cmd apt-get; then
    apt-get update -qq && apt-get install -y python3-venv && return 0
  fi
  if have_cmd dnf; then
    dnf install -y python3-venv 2>/dev/null || dnf install -y python3 && return 0
  fi
  if have_cmd yum; then
    yum install -y python3-venv 2>/dev/null || yum install -y python3 && return 0
  fi
  if have_cmd apk; then
    apk add --no-cache python3-venv 2>/dev/null || apk add --no-cache py3-virtualenv && return 0
  fi
  if have_cmd zypper; then
    zypper --non-interactive install python3-venv && return 0
  fi
  return 1
}

bootstrap_pip_get_pip() {
  ensure_download_tool || return 1
  _tmp="$(mktemp /tmp/get-pip.XXXXXX.py)"
  _url="$(get_pip_bootstrap_url)"
  if have_cmd curl; then
    curl -fsSL "$_url" -o "$_tmp" || return 1
  else
    wget -qO "$_tmp" "$_url" || return 1
  fi
  info "Bootstrapping pip via get-pip.py ..."
  _break="$(pip_extra_flags || true)"
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    if [ -n "$_break" ]; then
      run_py "$_tmp" --user --break-system-packages || return 1
    else
      run_py "$_tmp" --user || return 1
    fi
  elif [ -n "$_break" ]; then
    run_py "$_tmp" --break-system-packages || return 1
  else
    run_py "$_tmp" || return 1
  fi
  rm -f "$_tmp"
  pip_works
}

# Bootstrap pip on the system interpreter before venv creation (non-root may need --user).
ensure_minimal_base_pip() {
  should_use_venv || return 0
  [ -n "${VIRTUAL_ENV:-}" ] && return 0
  pip_works && return 0

  info "Bootstrapping minimal pip on $PYTHON (needed to create venv) ..."
  _saved_pip_user="${PIP_INSTALL_USER:-}"
  _saved_flag="${FLASHCLI_PIP_USER_FLAG:-}"
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    PIP_INSTALL_USER=1
    FLASHCLI_PIP_USER_FLAG="--user"
    export PIP_INSTALL_USER FLASHCLI_PIP_INSTALL_USER=1
  fi

  run_py -m ensurepip --upgrade >/dev/null 2>&1 \
    || run_py -m ensurepip >/dev/null 2>&1 \
    || true
  if ! pip_works; then
    try_pip3_same_interpreter || true
  fi
  if ! pip_works; then
    try_os_install_pip || true
    if [ -z "${VIRTUAL_ENV:-}" ] && PYTHON="$(discover_python)"; then
      export PYTHON
    fi
  fi
  if ! pip_works; then
    bootstrap_pip_get_pip || true
  fi

  PIP_INSTALL_USER="${_saved_pip_user:-0}"
  FLASHCLI_PIP_USER_FLAG="${_saved_flag:-}"
  export PIP_INSTALL_USER FLASHCLI_PIP_INSTALL_USER="${PIP_INSTALL_USER:-0}"
  pip_works
}

create_flashcli_venv_dir() {
  _venv="$1"
  _base="${2:-${FLASHCLI_BASE_PYTHON:-$PYTHON}}"
  _parent="$(dirname "$_venv")"

  if ! mkdir -p "$_parent" 2>/dev/null; then
    die "cannot create venv parent directory $_parent — check HOME (${HOME:-unset}) and disk permissions"
  fi

  if "$_base" -m venv "$_venv" 2>/dev/null; then
    return 0
  fi

  ensure_venv_module || true
  if "$_base" -m venv "$_venv" 2>/dev/null; then
    return 0
  fi

  if "$_base" -m virtualenv "$_venv" 2>/dev/null; then
    return 0
  fi

  if python_has_pip "$_base"; then
    info "Installing virtualenv package (python3-venv unavailable) ..."
    if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
      "$_base" -m pip install --user virtualenv >/dev/null 2>&1 || return 1
    else
      # Prefer plain install; --break-system-packages needs pip>=23.0.1 (PEP 668 hosts).
      if "$_base" -m pip install virtualenv >/dev/null 2>&1; then
        :
      elif "$_base" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages' \
        && "$_base" -m pip install --break-system-packages virtualenv >/dev/null 2>&1; then
        :
      else
        return 1
      fi
    fi
    "$_base" -m virtualenv "$_venv" 2>/dev/null && return 0
  fi
  return 1
}

# Default install target: ~/.flashcli/venv (opt out with FLASHCLI_USE_VENV=0).
activate_flashcli_venv_python() {
  _venv="$1"
  _py="${_venv}/bin/python3"
  if [ ! -x "$_py" ]; then
    _py="${_venv}/bin/python"
  fi
  [ -x "$_py" ] || return 1
  PYTHON="$_py"
  export PYTHON VIRTUAL_ENV="$_venv"
  PIP_INSTALL_USER=0
  FLASHCLI_PIP_USER_FLAG=""
  unset PYTHONNOUSERSITE
  export PIP_INSTALL_USER FLASHCLI_PIP_INSTALL_USER=0
  return 0
}

ensure_flashcli_venv() {
  should_use_venv || return 1
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"

  _venv="$(flashcli_venv_path)"
  _base_python="${FLASHCLI_BASE_PYTHON:-${PYTHON:-}}"

  _venv_py="${_venv}/bin/python3"
  [ ! -x "$_venv_py" ] && _venv_py="${_venv}/bin/python"
  if [ -x "$_venv_py" ]; then
    if activate_flashcli_venv_python "$_venv"; then
      if run_py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null \
        && pip_works; then
        info "[ok] using existing venv: $_venv ($PYTHON)"
        return 0
      fi
      warn "existing venv at $_venv is unusable — recreating"
      rm -rf "$_venv"
      PYTHON="$_base_python"
      export PYTHON
    fi
  fi

  ensure_minimal_base_pip || true
  info "Creating virtualenv at $_venv ..."
  if ! create_flashcli_venv_dir "$_venv" "$_base_python"; then
    die "cannot create venv at $_venv.
Reason: python3-venv/virtualenv unavailable and pip bootstrap failed.
Fix:
  apt install -y python3-venv          # Debian/Ubuntu (root)
  FLASHCLI_USE_VENV=0 ./install.sh     # install to system/user site instead"
  fi

  activate_flashcli_venv_python "$_venv" \
    || die "venv created but python missing in $_venv"
  if ! pip_works; then
    run_py -m ensurepip --upgrade >/dev/null 2>&1 || run_py -m ensurepip >/dev/null 2>&1 || true
  fi
  pip_works || die "venv created but pip missing in $_venv — try: rm -rf $_venv && re-run install.sh"
  info "[ok] using venv Python: $PYTHON"
}

# Match pip3 on PATH to the selected interpreter (some distros split python3 / pip3).
# Do not upgrade pip here — only confirm the same interpreter already has a working pip.
try_pip3_same_interpreter() {
  if ! have_cmd pip3; then
    return 1
  fi
  _pip3_py="$(pip3 -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
  if [ -n "$_pip3_py" ] && [ "$_pip3_py" = "$PYTHON" ]; then
    pip_works && return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
check_os() {
  os="$(uname -s 2>/dev/null || echo unknown)"
  case "$os" in
    Linux) info "[ok] OS: Linux" ;;
    *) die "requires Linux (pyproject/runtime); detected: $os" ;;
  esac
}

check_gpu() {
  if [ "${FLASHCLI_SKIP_GPU_CHECK:-0}" = "1" ]; then
    warn "FLASHCLI_SKIP_GPU_CHECK=1: skipping GPU check"
    return 0
  fi
  if ! have_cmd nvidia-smi; then
    if [ "${FLASHCLI_REQUIRE_GPU:-0}" = "1" ]; then
      die "cannot install flashcli — nvidia-smi not found (FLASHCLI_REQUIRE_GPU=1).
Reason: flashcli inference requires an NVIDIA GPU.
Fix: install NVIDIA driver + nvidia-smi, or unset FLASHCLI_REQUIRE_GPU to install CLI only"
    fi
    warn "nvidia-smi not found — install continues (GPU needed for inference; run flashcli doctor later)"
    return 0
  fi
  gpu_line="$(nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  if [ -z "$gpu_line" ]; then
    if [ "${FLASHCLI_REQUIRE_GPU:-0}" = "1" ]; then
      die "cannot install flashcli — nvidia-smi present but no GPU reported (FLASHCLI_REQUIRE_GPU=1)"
    fi
    warn "nvidia-smi present but no GPU reported — install continues"
    return 0
  fi
  info "[ok] GPU: $gpu_line"
}

check_python_version() {
  if ! run_py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    ver="$(run_py -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
    die "requires-python >=${REQUIRES_PYTHON_MIN} not met (found Python $ver via $PYTHON)"
  fi
  ver="$(run_py -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  if python_has_pip "$PYTHON"; then
    info "[ok] Python: $PYTHON ($ver, pip ready)"
  elif python_is_pep668 "$PYTHON" 2>/dev/null; then
    warn "Python $ver is PEP 668 externally-managed ($PYTHON) — will bootstrap pip or use venv"
    info "[ok] Python: $PYTHON ($ver)"
  else
    info "[ok] Python: $PYTHON ($ver, pip will be bootstrapped)"
  fi
}

# Upgrade pip only when below MIN_PIP_VERSION. Never pass modern CLI flags that
# older pip rejects (--root-user-action needs 22.1+; --break-system-packages 23.0.1+).
upgrade_pip_to_min() {
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"
  pip_works || return 1
  pip_version_ok && return 0

  _log="/tmp/flashcli-pip-upgrade-$$.log"
  _run_upgrade() {
    if run_py -m pip install "$@" >"$_log" 2>&1; then
      [ "$QUIET" = "1" ] || cat "$_log" >&2
      return 0
    fi
    [ "$QUIET" = "1" ] || cat "$_log" >&2
    return 1
  }

  set -- --upgrade "pip>=${MIN_PIP_VERSION}"
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    set -- --user "$@"
  fi
  if [ -z "${VIRTUAL_ENV:-}" ] && should_break_system_packages && pip_has_option break-system-packages; then
    set -- --break-system-packages "$@"
  fi

  if _run_upgrade "$@"; then
    rm -f "$_log"
    pip_version_ok && return 0
  fi

  # Fallback: unpinned upgrade (still only reached when below MIN_PIP_VERSION).
  set -- --upgrade pip
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    set -- --user "$@"
  fi
  if [ -z "${VIRTUAL_ENV:-}" ] && should_break_system_packages && pip_has_option break-system-packages; then
    set -- --break-system-packages "$@"
  fi
  if _run_upgrade "$@"; then
    rm -f "$_log"
    pip_version_ok && return 0
  fi
  rm -f "$_log"
  return 1
}

require_pip_min_or_die() {
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"
  if pip_works && pip_version_ok; then
    info "[ok] pip: $(run_py -m pip --version 2>/dev/null | head -n 1) (min ${MIN_PIP_VERSION})"
    return 0
  fi
  _have="$(run_py -m pip --version 2>/dev/null | head -n 1 || echo 'pip missing')"
  die "cannot proceed — need pip>=${MIN_PIP_VERSION} (have: ${_have}).
Reason: install uses PEP 508 git+URL #subdirectory=; pip below ${MIN_PIP_VERSION} is unsupported.
Fix:
  $PYTHON -m pip install -U 'pip>=${MIN_PIP_VERSION}'
  apt install -y python3-pip python3-venv && ./install.sh --mirror
  rm -rf \"\${HOME:-/root}/.flashcli/venv\" && ./install.sh --mirror"
}

# Bootstrap any pip onto $PYTHON (version may still be below MIN_PIP_VERSION).
bootstrap_pip_any() {
  # Prefer ensurepip without forcing an upgrade of an already-present pip tool chain.
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    run_py -m ensurepip --user >/dev/null 2>&1 || true
  else
    run_py -m ensurepip >/dev/null 2>&1 || true
  fi
  pip_works && return 0

  # Retry with --upgrade only when ensurepip installed nothing usable.
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    run_py -m ensurepip --upgrade --user >/dev/null 2>&1 || true
  else
    run_py -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi
  pip_works && return 0

  try_pip3_same_interpreter && return 0

  if try_os_install_pip; then
    if [ -z "${VIRTUAL_ENV:-}" ] && PYTHON="$(discover_python)"; then
      export PYTHON
    fi
    pip_works && return 0
  fi

  bootstrap_pip_get_pip && return 0

  if should_use_venv && [ -z "${VIRTUAL_ENV:-}" ] && ensure_flashcli_venv; then
    pip_works && return 0
  fi
  return 1
}

ensure_pip() {
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"

  if ! pip_works; then
    info "pip missing — installing a pip for $PYTHON (will keep it if >=${MIN_PIP_VERSION}) ..."
    bootstrap_pip_any \
      || die "cannot bootstrap pip for $PYTHON.
Reason: pip/ensurepip/get-pip and OS package install all failed.
This host may mix interpreters (e.g. Debian /usr/bin/python3.13 + /usr/local python3.12).
Fix:
  FLASHCLI_PYTHON=\$(command -v python3) ./install.sh
  apt install -y python3-pip python3-venv   # Debian/Ubuntu (root)
  ./install.sh --mirror                      # slow/blocked network
  FLASHCLI_BREAK_SYSTEM_PACKAGES=1 ./install.sh"
    info "[ok] pip bootstrapped: $(run_py -m pip --version 2>/dev/null | head -n 1)"
  fi

  if pip_version_ok; then
    info "[ok] pip: $(run_py -m pip --version 2>/dev/null | head -n 1) (meets min ${MIN_PIP_VERSION}; not upgrading)"
    return 0
  fi

  warn "pip is below required minimum ${MIN_PIP_VERSION}; upgrading only to satisfy that floor ..."
  if upgrade_pip_to_min; then
    info "[ok] pip upgraded to minimum: $(run_py -m pip --version 2>/dev/null | head -n 1)"
    return 0
  fi

  info "pip upgrade failed — retrying via get-pip.py ..."
  if bootstrap_pip_get_pip; then
    if pip_version_ok; then
      info "[ok] pip via get-pip.py: $(run_py -m pip --version 2>/dev/null | head -n 1)"
      return 0
    fi
    # get-pip may have installed something still oddly below floor — try one pin.
    if upgrade_pip_to_min; then
      info "[ok] pip via get-pip.py + pin: $(run_py -m pip --version 2>/dev/null | head -n 1)"
      return 0
    fi
  fi

  require_pip_min_or_die
}

# When installing to a PEP 668 system site without venv/--user, need pip that
# supports --break-system-packages (23.0.1+). Prefer failing early over upgrading.
assert_system_pip_capable() {
  [ -n "${VIRTUAL_ENV:-}" ] && return 0
  [ "${PIP_INSTALL_USER:-0}" = "1" ] && return 0
  python_is_pep668 "$PYTHON" 2>/dev/null || return 0
  if pip_has_option break-system-packages; then
    return 0
  fi
  die "cannot install into PEP 668 system Python without --break-system-packages (needs pip>=23.0.1).
Reason: this host marks $PYTHON as externally managed; default flashcli install uses a venv instead.
Fix:
  unset FLASHCLI_USE_VENV; ./install.sh          # default: ~/.flashcli/venv
  FLASHCLI_PIP_USER=1 ./install.sh               # or pip --user
  $PYTHON -m pip install -U 'pip>=23.0.1' && FLASHCLI_USE_VENV=0 FLASHCLI_BREAK_SYSTEM_PACKAGES=1 ./install.sh"
}

# packaging is required for version verification; install early if missing.
ensure_packaging() {
  if run_py -c "import packaging" 2>/dev/null; then
    return 0
  fi
  info "Installing packaging (needed to verify pyproject constraints) ..."
  set -- "packaging>=23.0"
  if [ -n "${FLASHCLI_PIP_USER_FLAG:-}" ]; then
    set -- "$@" --user
  fi
  do_pip_install "$@" \
    || die "cannot install packaging>=23.0.
Reason: pip/network/permissions failed after preflight (venv avoids most PEP 668 issues).
Fix:
  ./install.sh --mirror
  $PYTHON -m pip install -U 'packaging>=23.0'
  Check errors above"
}

ensure_build_deps() {
  if run_py -c "import setuptools, wheel" 2>/dev/null; then
    return 0
  fi
  info "Installing setuptools + wheel (git source build) ..."
  set -- "setuptools>=64" wheel
  if [ -n "${FLASHCLI_PIP_USER_FLAG:-}" ]; then
    set -- "$@" --user
  fi
  do_pip_install "$@" \
    || die "cannot install build dependencies (setuptools, wheel) — check network and pip errors above"
}

ensure_git() {
  if have_cmd git; then
    info "[ok] git: $(git --version 2>/dev/null | head -n 1)"
    return 0
  fi
  warn "git not found — attempting OS package install ..."
  if install_os_packages git && have_cmd git; then
    info "[ok] git: $(git --version 2>/dev/null | head -n 1) (installed)"
    return 0
  fi
  die "cannot install flashcli — git not found and auto-install failed.
Reason: pip install git+${REPO} requires git.
Fix:
  apt install -y git    # Debian/Ubuntu
  dnf install -y git    # RHEL/Fedora
  apk add git           # Alpine
  Re-run as root so install.sh can install git automatically"
}

# Install OS packages when running as root (best-effort across common distros).
install_os_packages() {
  [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] || return 1
  [ $# -gt 0 ] || return 1
  if apt_os_packages_skip || [ "$APT_OS_PACKAGES_DISABLED" -eq 1 ]; then
    return 1
  fi
  apply_os_package_mirrors
  if have_cmd apt-get; then
    info "Installing OS packages via apt: $*"
    if apt_get_update_safe && apt-get install -y "$@"; then
      return 0
    fi
    APT_OS_PACKAGES_DISABLED=1
    return 1
  fi
  if have_cmd dnf; then
    info "Installing OS packages via dnf: $*"
    dnf install -y "$@" && return 0
  fi
  if have_cmd yum; then
    info "Installing OS packages via yum: $*"
    yum install -y "$@" && return 0
  fi
  if have_cmd apk; then
    info "Installing OS packages via apk: $*"
    apk add --no-cache "$@" && return 0
  fi
  if have_cmd zypper; then
    info "Installing OS packages via zypper: $*"
    zypper --non-interactive install "$@" && return 0
  fi
  return 1
}

die_missing_host_tool() {
  _cmd="$1"
  _pkg="${2:-$_cmd}"
  printf '%s\n' "error: ${_cmd} not found — required for flashcli bundle zip workflows." >&2
  printf '%s\n' "error: Install ${_pkg}, then re-run. Examples:" >&2
  printf '%s\n' "error:   Debian/Ubuntu: apt install -y ${_pkg}" >&2
  printf '%s\n' "error:   RHEL/Fedora:   dnf install -y ${_pkg}" >&2
  printf '%s\n' "error:   Alpine:        apk add ${_pkg}" >&2
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    printf '%s\n' "error: Or re-run as root so install.sh can install OS packages automatically." >&2
  fi
  exit 1
}

# Like ensure_host_tool but warn-only (FlashHub pull/run does not need zip/rsync on the host).
ensure_host_tool_optional() {
  _cmd="$1"
  _pkg="${2:-$_cmd}"
  if have_cmd "$_cmd"; then
    case "$_cmd" in
      zip)
        info "[ok] zip: $(zip -v 2>/dev/null | head -n 1 || command -v zip)"
        ;;
      rsync)
        info "[ok] rsync: $(rsync --version 2>/dev/null | head -n 1 || command -v rsync)"
        ;;
      *)
        info "[ok] $_cmd: $(command -v "$_cmd")"
        ;;
    esac
    return 0
  fi
  warn "$_cmd not found — optional for FlashHub install (needed to pack local bundle zips)."
  if install_os_packages "$_pkg" && have_cmd "$_cmd"; then
    case "$_cmd" in
      zip)
        info "[ok] zip: $(zip -v 2>/dev/null | head -n 1 || command -v zip) (installed)"
        ;;
      rsync)
        info "[ok] rsync: $(rsync --version 2>/dev/null | head -n 1 || command -v rsync) (installed)"
        ;;
      *)
        info "[ok] $_cmd: $(command -v "$_cmd") (installed)"
        ;;
    esac
    return 0
  fi
  warn "Could not install ${_pkg} via OS package manager — continuing without it."
  warn "  To add later: apt install -y ${_pkg}  (or dnf/apk equivalent)"
  return 0
}

# Ensure a host CLI exists; auto-install OS package when root.
ensure_host_tool() {
  _cmd="$1"
  _pkg="${2:-$_cmd}"
  if have_cmd "$_cmd"; then
    case "$_cmd" in
      zip)
        info "[ok] zip: $(zip -v 2>/dev/null | head -n 1 || command -v zip)"
        ;;
      rsync)
        info "[ok] rsync: $(rsync --version 2>/dev/null | head -n 1 || command -v rsync)"
        ;;
      *)
        info "[ok] $_cmd: $(command -v "$_cmd")"
        ;;
    esac
    return 0
  fi
  warn "$_cmd not found — attempting OS package install ($_pkg) ..."
  if install_os_packages "$_pkg" && have_cmd "$_cmd"; then
    case "$_cmd" in
      zip)
        info "[ok] zip: $(zip -v 2>/dev/null | head -n 1 || command -v zip) (installed)"
        ;;
      rsync)
        info "[ok] rsync: $(rsync --version 2>/dev/null | head -n 1 || command -v rsync) (installed)"
        ;;
      *)
        info "[ok] $_cmd: $(command -v "$_cmd") (installed)"
        ;;
    esac
    return 0
  fi
  die_missing_host_tool "$_cmd" "$_pkg"
}

ensure_zip_rsync() {
  ensure_host_tool_optional zip zip
  ensure_host_tool_optional rsync rsync
}

check_network() {
  ensure_git_remote_ready
}

# Retry git reachability — Gitee anonymous HTTPS is occasionally flaky (auth challenge / rate-limit).
git_ref_reachable_with_retries() {
  _repo="$1"
  _ref="$2"
  _tries="${FLASHCLI_GIT_RETRIES:-3}"
  case "$_tries" in
    ''|*[!0-9]*) _tries=3 ;;
  esac
  [ "$_tries" -ge 1 ] || _tries=3
  _sleep="${FLASHCLI_GIT_RETRY_SLEEP:-2}"
  _i=1
  while [ "$_i" -le "$_tries" ]; do
    if git_ref_reachable "$_repo" "$_ref"; then
      return 0
    fi
    if [ "$_i" -lt "$_tries" ]; then
      _http="$(probe_git_upload_pack_http "$_repo" | tr -d '\n')"
      warn "git remote not reachable (try ${_i}/${_tries}): ${_repo} (upload-pack HTTP ${_http}) — retrying in ${_sleep}s…"
      sleep "$_sleep" 2>/dev/null || true
    fi
    _i=$((_i + 1))
  done
  return 1
}

_github_install_url_via_proxy() {
  _proxy="${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}"
  case "$_proxy" in
    ""|auto|0|false|no|off)
      printf '%s\n' "$DEFAULT_REPO_GITHUB"
      return 0
      ;;
  esac
  _proxy="${_proxy%/}/"
  printf '%s%s\n' "$_proxy" "$DEFAULT_REPO_GITHUB"
}

# Try one git URL; on success set REPO and return 0.
_try_git_repo() {
  _candidate="$1"
  _label="$2"
  [ -n "$_candidate" ] || return 1
  info "Trying git remote (${_label}): ${_candidate} @ ${REF}"
  if git_ref_reachable_with_retries "$_candidate" "$REF"; then
    REPO="$_candidate"
    export FLASHCLI_INSTALL_REPO="$REPO"
    info "[ok] git remote reachable (${_label}): $REPO ($REF)"
    return 0
  fi
  _http="$(probe_git_upload_pack_http "$_candidate" | tr -d '\n')"
  warn "git remote not reachable (${_label}): ${_candidate} (upload-pack HTTP ${_http})"
  return 1
}

# Fail early if pip's git+URL cannot resolve.
# --mirror (default official path): Gitee → GitHub → GitHub proxy
# otherwise:                       GitHub → Gitee → GitHub proxy
ensure_git_remote_ready() {
  if ! have_cmd git; then
    return 0
  fi

  _gh_proxy="$(_github_install_url_via_proxy)"

  # Custom non-official --repo: only probe that URL.
  case "$REPO" in
    "$DEFAULT_REPO_GITHUB"|"$DEFAULT_REPO_GITEE"|https://github.com/aodianyun/flashcli.git|https://gitee.com/aodiansoft/flashcli.git)
      ;;
    *"github.com/aodianyun/flashcli"*|*"gitee.com/aodiansoft/flashcli"*)
      ;;
    *)
      if [ "$REPO_FROM_USER" -eq 1 ]; then
        info "Checking git remote (user --repo): $REPO @ $REF"
        _try_git_repo "$REPO" "user" && return 0
        _http="$(probe_git_upload_pack_http "$REPO" | tr -d '\n')"
        die "cannot reach git remote ${REPO} @ ${REF} (upload-pack HTTP ${_http})"
      fi
      ;;
  esac

  # --github / explicit GitHub: GitHub first even if --mirror (mirrors still apply to pip/HF).
  # --mirror (default) / --gitee: Gitee first.
  # plain install: GitHub first.
  _prefer_gitee=0
  if [ "$REPO_FROM_USER" -eq 1 ]; then
    case "$REPO" in
      *gitee.com*) _prefer_gitee=1 ;;
      *) _prefer_gitee=0 ;;
    esac
  elif mirror_mode_enabled; then
    _prefer_gitee=1
  fi

  if [ "$_prefer_gitee" -eq 1 ]; then
    info "Checking git remotes: Gitee → GitHub → GitHub proxy @ $REF"
    _try_git_repo "$DEFAULT_REPO_GITEE" "gitee" && return 0
    _try_git_repo "$DEFAULT_REPO_GITHUB" "github" && return 0
    if [ "$_gh_proxy" != "$DEFAULT_REPO_GITHUB" ]; then
      _try_git_repo "$_gh_proxy" "github-proxy" && return 0
    fi
  else
    info "Checking git remotes: GitHub → Gitee → GitHub proxy @ $REF"
    _try_git_repo "$DEFAULT_REPO_GITHUB" "github" && return 0
    _try_git_repo "$DEFAULT_REPO_GITEE" "gitee" && return 0
    if [ "$_gh_proxy" != "$DEFAULT_REPO_GITHUB" ]; then
      _try_git_repo "$_gh_proxy" "github-proxy" && return 0
    fi
  fi

  die "cannot reach any git remote for flashcli @ ${REF}.
Tried: ${DEFAULT_REPO_GITEE}, ${DEFAULT_REPO_GITHUB}, and GitHub proxy (${_gh_proxy}).
Gitee may return HTTP 401 for some datacenter IPs (not local credential pollution).
Fix:
  ./install.sh --github --ref ${REF}
  FLASHCLI_GIT_PROXY=https://gh-proxy.com/ ./install.sh --mirror --ref ${REF}
  GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote ${DEFAULT_REPO_GITHUB} ${REF}"
}

# Fail early if PyPI (or configured mirror) cannot serve packages.
check_pypi_ready() {
  info "Checking PyPI / index reachability ..."
  _pypi_probe() {
    PIP_INDEX_URL="${PIP_INDEX_URL:-}" "$PYTHON" - <<'PY'
import os, urllib.error, urllib.request

index = (os.environ.get("PIP_INDEX_URL") or "https://pypi.org/simple").rstrip("/")
if index.endswith("/simple"):
    url = index + "/pip/"
elif "/simple/" in index:
    url = index if index.endswith("/") else index + "/"
else:
    url = "https://pypi.org/simple/pip/"

try:
    req = urllib.request.Request(url, headers={"User-Agent": "flashcli-install/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read(512)
except Exception as exc:
    print(str(exc), flush=True)
    raise SystemExit(1)
raise SystemExit(0)
PY
  }

  if _pypi_probe; then
    info "[ok] package index reachable (${PIP_INDEX_URL:-https://pypi.org/simple})"
    return 0
  fi

  if ! mirror_mode_enabled && [ -z "${PIP_INDEX_URL:-}" ]; then
    warn "default PyPI unreachable — enabling China mirrors and retrying"
    USE_MIRROR=1
    export FLASHCLI_USE_MIRROR="$USE_MIRROR"
    apply_mirror_endpoints
    if _pypi_probe; then
      info "[ok] package index reachable (${PIP_INDEX_URL:-mirror})"
      return 0
    fi
  fi

  # Unpinned --mirror: walk tuna→aliyun→ustc→tencent→huawei on preflight failure.
  if pypi_auto_failover_enabled; then
    _failed_label="${MIRROR_PIP_LABEL:-tuna}"
    for _lab in $(pypi_failover_labels_after "$_failed_label"); do
      warn "package index ${_failed_label} unreachable — trying ${_lab} ..."
      switch_active_pypi_mirror "$_lab" || continue
      if _pypi_probe; then
        info "[ok] package index reachable (${PIP_INDEX_URL})"
        return 0
      fi
      _failed_label="$_lab"
    done
  fi

  die "cannot reach PyPI/package index — pip install would fail mid-way.
Reason: network blocked, DNS failure, or mirror unreachable (${PIP_INDEX_URL:-https://pypi.org/simple}).
Fix:
  ./install.sh --mirror
  ./install.sh --pip-mirror aliyun
  ./install.sh --mirror --pip-mirror pypi
  export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
  Check proxy/firewall; retry when network is available"
}

# Final gate: only start the real install once the environment is known-good.
assert_install_ready() {
  info "Preflight gate: confirming install can complete ..."
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"

  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux) ;;
    *) die "requires Linux; detected: $(uname -s 2>/dev/null || echo unknown)" ;;
  esac

  if ! run_py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    die "requires Python >= ${REQUIRES_PYTHON_MIN} (interpreter: $PYTHON)"
  fi

  if should_use_venv && [ -z "${VIRTUAL_ENV:-}" ]; then
    die "venv mode is on but VIRTUAL_ENV is unset — venv bootstrap failed.
Fix: apt install -y python3-venv && rm -rf \"\${HOME:-/root}/.flashcli/venv\" && ./install.sh
  Or: FLASHCLI_USE_VENV=0 ./install.sh"
  fi

  require_pip_min_or_die
  assert_system_pip_capable

  if ! run_py -c "import packaging" 2>/dev/null; then
    die "packaging is not importable after ensure_packaging — cannot verify constraints"
  fi

  if ! have_cmd git; then
    die "git is required to install flashcli from git+URL"
  fi

  check_install_target
  info "[ok] preflight gate passed — starting package install"
}

git_ref_reachable() {
  _repo="$1"
  _ref="$2"
  # branch
  if run_git_timeout ls-remote --exit-code --heads "$_repo" "$_ref" >/dev/null 2>&1; then
    return 0
  fi
  # tag
  if run_git_timeout ls-remote --exit-code --tags "$_repo" "$_ref" >/dev/null 2>&1; then
    return 0
  fi
  # commit sha (short/full): match object id at line start
  case "$_ref" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]*)
      run_git_timeout ls-remote "$_repo" 2>/dev/null | awk -v want="$_ref" '
        BEGIN { ok=1 }
        {
          oid=$1
          if (index(oid, want) == 1) {
            ok=0
            exit
          }
        }
        END { exit ok }
      ' >/dev/null 2>&1 && return 0
      ;;
  esac
  return 1
}

check_install_target() {
  "$PYTHON" - <<'PY' || die "install target not writable — check disk space and permissions (venv: ${VIRTUAL_ENV:-system site})"
import os, sys, sysconfig, tempfile

def ok(p):
    try:
        os.makedirs(p, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=p)
        os.close(fd)
        os.unlink(path)
        return True
    except OSError:
        return False

use_user = os.environ.get("FLASHCLI_PIP_INSTALL_USER") == "1"
if use_user:
    base = sysconfig.get_path("userbase")
    scripts = sysconfig.get_path("scripts", "posix_user")
else:
    scripts = sysconfig.get_path("scripts")
    base = sys.prefix

if not ok(scripts):
    raise SystemExit(f"cannot write console scripts dir: {scripts}")
site = sysconfig.get_path("purelib") if not use_user else sysconfig.get_path("purelib", "posix_user")
if not ok(site):
    raise SystemExit(f"cannot write site-packages: {site}")
print(f"[ok] install target writable: scripts={scripts}", flush=True)
PY
}

pip_scripts_dir() {
  use_user="$1"
  run_py -c "
import sysconfig
print(sysconfig.get_path('scripts', 'posix_user') if '${use_user}' == '1'
      else sysconfig.get_path('scripts'))
" 2>/dev/null
}

in_virtualenv() {
  [ -n "${VIRTUAL_ENV:-}" ] && return 0
  run_py -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' 2>/dev/null
}

should_pip_install_user() {
  if in_virtualenv; then
    return 1
  fi
  case "${FLASHCLI_PIP_USER:-auto}" in
    0 | false | no) return 1 ;;
    1 | true | yes) return 0 ;;
  esac
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
    return 1
  fi
  return 0
}

set_pip_install_mode() {
  if should_pip_install_user; then
    PIP_INSTALL_USER=1
    FLASHCLI_PIP_USER_FLAG="--user"
    unset PYTHONNOUSERSITE
  else
    PIP_INSTALL_USER=0
    FLASHCLI_PIP_USER_FLAG=""
    PYTHONNOUSERSITE=1
    export PYTHONNOUSERSITE
  fi
  export PIP_INSTALL_USER FLASHCLI_PIP_INSTALL_USER="$PIP_INSTALL_USER"
}

preflight_pyproject() {
  info "Pre-checking pyproject.toml [project] constraints ..."
  "$PYTHON" - <<'PY' || die "pre-install pyproject check failed"
import os, sys

min_ver = tuple(int(x) for x in os.environ.get("FLASHCLI_REQUIRES_PYTHON_MIN", "3.10").split("."))
if sys.version_info < min_ver:
    raise SystemExit(
        f"requires-python >={'.'.join(map(str, min_ver))} required; "
        f"got {sys.version_info.major}.{sys.version_info.minor}"
    )
try:
    import packaging  # noqa: F401
except ImportError:
    raise SystemExit("packaging not importable — run ensure_packaging first")
print("[ok] pre-install: Python version + packaging", flush=True)
PY
}

warn_python2_only() {
  for cmd in python python2; do
    if have_cmd "$cmd" && "$cmd" -c 'import sys; exit(0 if sys.version_info[0] < 3 else 1)' 2>/dev/null; then
      warn "found $cmd but flashcli requires Python >= ${REQUIRES_PYTHON_MIN} (not Python 2)"
    fi
  done
}

run_preflight() {
  info "=== Preflight: verify this host can finish install before downloading packages ==="
  ensure_home
  if [ "${FLASHCLI_SKIP_ENV_CHECK:-0}" = "1" ]; then
    warn "FLASHCLI_SKIP_ENV_CHECK=1: minimal pre-flight only"
    resolve_python
    ensure_minimal_base_pip || true
    if should_use_venv; then
      ensure_flashcli_venv
    fi
    set_pip_install_mode
    ensure_git || true
    check_pypi_ready || true
    ensure_pip
    ensure_packaging
    assert_install_ready
    return 0
  fi
  check_os
  check_gpu
  warn_python2_only
  resolve_python
  ensure_minimal_base_pip || true
  if should_use_venv; then
    ensure_flashcli_venv
  else
    ensure_flashcli_venv || true
  fi
  set_pip_install_mode
  check_python_version
  # Reachability before upgrading pip / installing packaging (auto-enables mirrors).
  ensure_git
  ensure_zip_rsync
  check_network
  check_pypi_ready
  ensure_pip
  ensure_packaging
  preflight_pyproject
  ensure_build_deps
  assert_install_ready
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
cleanup_stale_user_install() {
  [ "$PIP_INSTALL_USER" = "0" ] || return 0
  user_bin="${HOME:-}/.local/bin"
  if [ ! -x "${user_bin}/flashcli" ] \
    && ! run_py -m pip show flashcli >/dev/null 2>&1; then
    return 0
  fi
  info "Removing stale pip --user flashcli ..."
  run_py -m pip uninstall -y flashcli 2>/dev/null || true
  rm -f "${user_bin}/flashcli" "${user_bin}/flash" 2>/dev/null || true
}

_pip_install_flashcli_spec() {
  _spec="$1"
  set -- --upgrade --force-reinstall
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    set -- "$@" --user
  fi
  [ "$QUIET" = "1" ] && set -- "$@" -q
  set -- "$@" "$_spec"
  do_pip_install "$@"
}

# flashcli-bundle is not on PyPI; install it from git first, then flashcli with --no-deps.
_pip_install_flashcli_main() {
  _spec="git+${REPO}@${REF}"
  set -- --upgrade --force-reinstall --no-deps
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    set -- "$@" --user
  fi
  [ "$QUIET" = "1" ] && set -- "$@" -q
  set -- "$@" "$_spec"
  do_pip_install "$@"
}

# flashcli is installed with --no-deps (flashcli-bundle is git-only); install [project] deps here.
install_flashcli_runtime_deps() {
  info "Installing flashcli host runtime dependencies (typer, huggingface_hub, …) ..."
  set -- --upgrade
  if [ -n "${FLASHCLI_PIP_USER_FLAG:-}" ]; then
    set -- "$@" --user
  fi
  set -- "$@" \
    'typer>=0.12' \
    'pyyaml>=6.0' \
    'packaging>=23.0' \
    'huggingface_hub>=0.26' \
    'modelscope>=1.11' \
    'tqdm>=4.66'
  do_pip_install "$@" \
    || die "cannot install flashcli host runtime dependencies — check pip/network errors above"
  if run_py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
    :
  else
    set -- --upgrade
    if [ -n "${FLASHCLI_PIP_USER_FLAG:-}" ]; then
      set -- "$@" --user
    fi
    set -- "$@" "tomli>=2.0"
    do_pip_install "$@" \
      || die "cannot install tomli>=2.0 (required for Python < 3.11)"
  fi
  info "[ok] runtime dependencies installed"
}

try_mirror_repo_fallback() {
  [ "$REPO_FROM_USER" -eq 1 ] && return 1
  case "$REPO" in
    "$DEFAULT_REPO_GITHUB"|https://github.com/aodianyun/flashcli.git) ;;
    *) return 1 ;;
  esac
  warn "GitHub pip install failed — retrying with Gitee + mirror endpoints ..."
  REPO="$DEFAULT_REPO_GITEE"
  USE_MIRROR=1
  export FLASHCLI_INSTALL_REPO="$REPO" FLASHCLI_USE_MIRROR="$USE_MIRROR"
  apply_mirror_endpoints
  return 0
}

install_flashcli() {
  # Install runtime deps first so re-runs do not trigger pip "dependency conflicts"
  # when flashcli (already in venv, --no-deps) is checked during flashcli-bundle install.
  install_flashcli_runtime_deps

  bundle_spec="flashcli-bundle @ git+${REPO}@${REF}#subdirectory=flashcli-bundle"
  info "Installing protocol package: $bundle_spec"
  if ! _pip_install_flashcli_spec "$bundle_spec"; then
    if try_mirror_repo_fallback; then
      bundle_spec="flashcli-bundle @ git+${REPO}@${REF}#subdirectory=flashcli-bundle"
      info "Retrying protocol install: $bundle_spec"
      _pip_install_flashcli_spec "$bundle_spec" || die "pip install failed for $bundle_spec"
    else
      die "pip install failed for $bundle_spec (flashcli-bundle subdirectory missing in repo?)"
    fi
  fi

  spec="git+${REPO}@${REF}"
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    info "Installing $spec (--no-deps) → $(pip_scripts_dir 1) (pip --user; may take a few minutes) ..."
  elif [ -n "${VIRTUAL_ENV:-}" ]; then
    info "Installing $spec (--no-deps) → $(pip_scripts_dir 0) (venv; may take a few minutes) ..."
  else
    cleanup_stale_user_install
    info "Installing $spec (--no-deps) → $(pip_scripts_dir 0) (system site; may take a few minutes) ..."
  fi

  if _pip_install_flashcli_main; then
    info "[ok] pip install finished"
    return 0
  fi

  if try_mirror_repo_fallback; then
    info "Retrying install: git+${REPO}@${REF} (--no-deps)"
    if _pip_install_flashcli_main; then
      info "[ok] pip install finished (mirror fallback)"
      return 0
    fi
  fi

  die "pip install failed for git+${REPO}@${REF} (--no-deps; flashcli-bundle must be installed first).
Reason: git clone or pip dependency install failed (network, firewall, disk, or git auth).
Fix:
  ./install.sh --mirror
  ./install.sh --gitee
  export FLASHCLI_USE_MIRROR=1 ./install.sh
  Check errors above for the first failing package"
}

# ---------------------------------------------------------------------------
# Post-install: verify pyproject + optional repair
# ---------------------------------------------------------------------------
verify_and_repair_pyproject() {
  info "Verifying pyproject.toml [project] (install mode=${PIP_INSTALL_USER}) ..."
  export FLASHCLI_INSTALL_REPO="$REPO"
  export FLASHCLI_INSTALL_REF="$REF"
  export FLASHCLI_NO_REPAIR="${FLASHCLI_NO_REPAIR:-0}"
  export FLASHCLI_PYPROJECT_DEPS="$(_flashcli_pyproject_deps_list)"

  if "$PYTHON" - <<'PY'
import os
import subprocess
import sys

REPAIR = os.environ.get("FLASHCLI_NO_REPAIR", "0") != "1"
PIP_USER = os.environ.get("FLASHCLI_PIP_INSTALL_USER") == "1"
IMPORT_NAMES = {"pyyaml": "yaml", "huggingface-hub": "huggingface_hub"}
CANONICAL_DEPS = [
    ln.strip()
    for ln in os.environ.get("FLASHCLI_PYPROJECT_DEPS", "").splitlines()
    if ln.strip()
]


def err(msg: str) -> None:
    errors.append(msg)


errors: list[str] = []


def pip_install(*specs: str) -> bool:
    if not specs:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if PIP_USER:
        cmd.append("--user")
    cmd.extend(specs)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err(f"pip install failed: {' '.join(specs)}\n{(r.stderr or r.stdout or '').strip()}")
        return False
    return True


def nvidia_dali_installed() -> bool:
    try:
        from importlib.metadata import distributions
    except ImportError:
        return False
    for dist in distributions():
        name = (dist.metadata.get("Name") or dist.name or "").lower()
        if name.startswith("nvidia-dali"):
            return True
    return False


def packaging_spec_for_env() -> str:
    """flashcli needs packaging>=23.0; NVIDIA DALI images often pin packaging<=25.0."""
    if nvidia_dali_installed():
        return "packaging>=23.0,<=25.0"
    return "packaging>=23.0"


def reconcile_packaging_with_nvidia_stack() -> None:
    if not nvidia_dali_installed():
        return
    print(
        "[info] NVIDIA DALI detected — aligning packaging with flashcli and DALI (>=23.0,<=25.0)",
        file=sys.stderr,
    )
    pip_install(packaging_spec_for_env())


def check_pip_conflicts() -> None:
    chk = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
    )
    if chk.returncode == 0:
        print("[ok] pip check", file=sys.stderr)
        return

    text = ((chk.stdout or "") + (chk.stderr or "")).strip()
    strict = os.environ.get("FLASHCLI_STRICT_PIP_CHECK", "0") == "1"
    if strict:
        err(f"pip check:\n{text}")
        return

    flashcli_issues: list[str] = []
    other_issues: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pkg = line.split()[0].lower().replace("_", "-") if line.split() else ""
        if pkg == "flashcli":
            flashcli_issues.append(line)
        else:
            other_issues.append(line)

    if flashcli_issues:
        err("pip check (flashcli):\n" + "\n".join(flashcli_issues))
    if other_issues:
        print(
            "[warn] pip check: other packages in this environment (flashcli install is ok):",
            file=sys.stderr,
        )
        for line in other_issues:
            print(f"[warn]   {line}", file=sys.stderr)


def check_import(name: str) -> None:
    mod = IMPORT_NAMES.get(name.lower(), name.lower().replace("-", "_"))
    try:
        __import__(mod)
    except ImportError as exc:
        err(f"{name}: cannot import {mod} ({exc})")


def collect_errors() -> list[str]:
    errors.clear()
    try:
        from importlib.metadata import distribution, entry_points, version
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError as exc:
        err(f"packaging/importlib.metadata unavailable ({exc})")
        return list(errors)

    if sys.version_info < (3, 10):
        err(f"requires-python >=3.10 not met (running {sys.version_info[:2]})")

    try:
        dist = distribution("flashcli")
    except Exception as exc:
        err(f"flashcli not installed: {exc}")
        return list(errors)

    print(f"[ok] flashcli {version('flashcli')}", file=sys.stderr)

    try:
        import flashcli_bundle  # noqa: F401

        print(f"[ok] flashcli-bundle {version('flashcli-bundle')}", file=sys.stderr)
    except ImportError as exc:
        err(
            "flashcli-bundle not installed (git-only, not PyPI). "
            "Re-run install.sh or: pip install "
            f"'flashcli-bundle @ git+{os.environ.get('FLASHCLI_INSTALL_REPO', '<repo>')}"
            f"@{os.environ.get('FLASHCLI_INSTALL_REF', 'main')}#subdirectory=flashcli-bundle'"
            f" ({exc})"
        )
        return list(errors)

    req_py = dist.metadata.get("Requires-Python") or ">=3.10"
    try:
        spec_py = SpecifierSet(req_py)
        ver = Version(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        if ver not in spec_py:
            err(f"Requires-Python {req_py!r} not satisfied by {ver}")
    except Exception as exc:
        err(f"Requires-Python check failed: {exc}")

    requires = dist.requires or []
    if not requires:
        err("flashcli wheel missing Requires-Dist metadata")

    for req_str in requires:
        try:
            req = Requirement(req_str)
        except Exception as exc:
            err(f"bad requirement metadata: {req_str!r} ({exc})")
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        name = req.name
        try:
            inst = version(name)
        except Exception:
            err(f"missing dependency: {req_str}")
            continue
        if req.specifier and inst not in req.specifier:
            err(f"{name}=={inst} does not satisfy {req.specifier} (need {req_str})")
        check_import(name)

    expected = "flashcli.cli:app"
    alt_expected = "flashcli.cli:main"
    found = {
        ep.name
        for ep in entry_points(group="console_scripts")
        if ep.name == "flashcli" and ep.value in (expected, alt_expected)
    }
    missing = {"flashcli"} - found
    if missing:
        err(f"[project.scripts] missing: {', '.join(sorted(missing))}")

    try:
        from flashcli.cli import app  # noqa: F401
    except ImportError as exc:
        try:
            from flashcli.cli import main  # noqa: F401
        except ImportError:
            err(f"flashcli.cli import failed: {exc}")

    reconcile_packaging_with_nvidia_stack()
    check_pip_conflicts()

    import shutil as _shutil

    hf_bin = _shutil.which("hf") or _shutil.which("huggingface-cli")
    if hf_bin:
        print(f"[ok] Hub CLI on PATH: {hf_bin}", file=sys.stderr)
    else:
        probe = subprocess.run(
            [sys.executable, "-m", "huggingface_hub.cli.hf", "--help"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            print(
                "[ok] Hub CLI: python -m huggingface_hub.cli.hf "
                "(add pip scripts dir to PATH for `hf` command)",
                file=sys.stderr,
            )
        else:
            err(
                "Hub CLI missing (need huggingface_hub>=0.26). "
                "Fix: python -m pip install -U 'huggingface_hub>=0.26'"
            )

    return list(errors)


def repair_once() -> None:
    repo = os.environ.get("FLASHCLI_INSTALL_REPO", "")
    ref = os.environ.get("FLASHCLI_INSTALL_REF", "main")
    # Runtime deps before flashcli-bundle to avoid pip conflict noise on re-run.
    specs = []
    for raw in CANONICAL_DEPS:
        s = raw.strip().strip("'\"")
        if not s:
            continue
        if s.startswith("packaging"):
            specs.append(packaging_spec_for_env())
        else:
            specs.append(s)
    if sys.version_info < (3, 11):
        specs.append("tomli>=2.0")
    print("[info] attempting automatic repair (runtime deps, flashcli-bundle, flashcli --no-deps) ...", file=sys.stderr)
    if not pip_install(*specs):
        return
    if repo:
        if not pip_install(
            f"flashcli-bundle @ git+{repo}@{ref}#subdirectory=flashcli-bundle"
        ):
            return
    if not repo:
        return
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "--no-deps",
        f"git+{repo}@{ref}",
    ]
    if PIP_USER:
        cmd.append("--user")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err(
            f"pip install --no-deps flashcli failed:\n{(r.stderr or r.stdout or '').strip()}"
        )


errors = collect_errors()
if errors and REPAIR:
    repair_once()
    errors = collect_errors()

if errors:
    print("error: environment does not satisfy pyproject.toml [project]:", file=sys.stderr)
    for e in errors:
        print(f"error:   - {e}", file=sys.stderr)
    repo = os.environ.get("FLASHCLI_INSTALL_REPO", "")
    ref = os.environ.get("FLASHCLI_INSTALL_REF", "main")
    print("error: manual fix:", file=sys.stderr)
    if repo:
        print(
            f"error:   {sys.executable} -m pip install "
            f"'flashcli-bundle[infer] @ git+{repo}@{ref}#subdirectory=flashcli-bundle'",
            file=sys.stderr,
        )
    print(
        f"error:   {sys.executable} -m pip install --force-reinstall --no-deps 'git+{repo}@{ref}'",
        file=sys.stderr,
    )
    _deps = " ".join(f"'{s.strip()}'" for s in CANONICAL_DEPS if s.strip())
    print(f"error:   {sys.executable} -m pip install --upgrade {_deps}", file=sys.stderr)
    raise SystemExit(1)

print("[ok] pyproject.toml [project] satisfied", file=sys.stderr)
PY
  then
    :
  else
    die "post-install verification failed (see errors above)"
  fi
}

# ---------------------------------------------------------------------------
# CLI on PATH (critical for ./install.sh in parent shell)
# ---------------------------------------------------------------------------
flashcli_script_is_runnable() {
  _f="$1"
  [ -n "$_f" ] && [ -f "$_f" ] && "$_f" --help >/dev/null 2>&1
}

_find_flashcli_script_in_dir() {
  _d="$1"
  [ -n "$_d" ] || return 1
  [ -f "${_d}/flashcli" ] || return 1
  printf '%s' "${_d}/flashcli"
}

flashcli_script_path() {
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    for d in "$(pip_scripts_dir 1)" "${HOME:-}/.local/bin"; do
      _f="$(_find_flashcli_script_in_dir "$d" 2>/dev/null || true)"
      [ -n "$_f" ] && printf '%s' "$_f" && return 0
    done
    return 1
  fi
  for d in /usr/local/bin /usr/bin "$(pip_scripts_dir 0)"; do
    _f="$(_find_flashcli_script_in_dir "$d" 2>/dev/null || true)"
    [ -n "$_f" ] && printf '%s' "$_f" && return 0
  done
  return 1
}

write_module_cli_wrapper() {
  _dest="$1"
  _py="$2"
  _mod="$3"
  _parent="$(dirname "$_dest")"
  mkdir -p "$_parent" 2>/dev/null || return 1
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' "exec \"$_py\" -m $_mod \"\$@\""
  } > "$_dest" || return 1
  chmod 755 "$_dest" 2>/dev/null || chmod +x "$_dest" 2>/dev/null || return 1
}

install_cli_wrappers_in_dir() {
  _dir="$1"
  write_module_cli_wrapper "${_dir}/flashcli" "$PYTHON" "flashcli.cli" || return 1
  rm -f "${_dir}/flash" 2>/dev/null || true
  if run_py -c "import huggingface_hub" 2>/dev/null; then
    write_module_cli_wrapper "${_dir}/hf" "$PYTHON" "huggingface_hub.cli.hf" || true
    rm -f "${_dir}/huggingface-cli" 2>/dev/null || true
    ln -sf hf "${_dir}/huggingface-cli" 2>/dev/null || true
  fi
}

# Real wrapper scripts (not symlinks into ~/.flashcli/venv) — works when /root is noexec.
ensure_global_cli_wrappers() {
  [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] || return 0
  _installed=0
  for _dir in /usr/local/bin /usr/bin; do
    [ -d "$(dirname "$_dir")" ] || continue
    if install_cli_wrappers_in_dir "$_dir"; then
      info "Installed CLI wrappers → $_dir"
      _installed=1
    fi
  done
  [ "$_installed" -eq 1 ]
}

prepend_path_dir() {
  _dir="$1"
  [ -n "$_dir" ] || return 0
  path_has_dir "$_dir" && return 0
  PATH="${_dir}${PATH:+:${PATH}}"
  export PATH
}

persist_path_config() {
  cli_dir="$1"
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] && [ -d /etc/profile.d ]; then
    {
      printf '%s\n' "export PATH=\"${cli_dir}:\$PATH\""
      if mirror_mode_enabled; then
        printf '%s\n' "export FLASHCLI_USE_MIRROR=1"
        [ -n "${PIP_INDEX_URL:-}" ] && printf '%s\n' "export PIP_INDEX_URL=\"${PIP_INDEX_URL}\""
        [ -n "${PIP_TRUSTED_HOST:-}" ] && printf '%s\n' "export PIP_TRUSTED_HOST=\"${PIP_TRUSTED_HOST}\""
        [ -n "${HF_ENDPOINT:-}" ] && printf '%s\n' "export HF_ENDPOINT=\"${HF_ENDPOINT}\""
        printf '%s\n' "export FLASHCLI_PREFER_HF_MIRROR=1"
      fi
    } > /etc/profile.d/flashcli.sh
    info "Wrote /etc/profile.d/flashcli.sh (PATH + mirror env for login shells)"
    return 0
  fi
  path_has_dir "$cli_dir" && ! mirror_mode_enabled && return 0
  if [ -n "${HOME:-}" ]; then
    for rc in "${HOME}/.profile" "${HOME}/.bashrc"; do
      if [ -f "$rc" ]; then
        if ! path_has_dir "$cli_dir" && ! grep -Fq "$cli_dir" "$rc" 2>/dev/null; then
          printf '\n# flashcli install.sh\nexport PATH="%s:$PATH"\n' "$cli_dir" >> "$rc"
          info "Appended PATH to $rc"
        fi
        if mirror_mode_enabled && ! grep -Fq 'HF_ENDPOINT=' "$rc" 2>/dev/null; then
          {
            printf '\n# flashcli install.sh (mirror endpoints)\n'
            printf '%s\n' 'export FLASHCLI_USE_MIRROR=1'
            [ -n "${PIP_INDEX_URL:-}" ] && printf 'export PIP_INDEX_URL="%s"\n' "$PIP_INDEX_URL"
            [ -n "${PIP_TRUSTED_HOST:-}" ] && printf 'export PIP_TRUSTED_HOST="%s"\n' "$PIP_TRUSTED_HOST"
            [ -n "${HF_ENDPOINT:-}" ] && printf 'export HF_ENDPOINT="%s"\n' "$HF_ENDPOINT"
            printf '%s\n' 'export FLASHCLI_PREFER_HF_MIRROR=1'
          } >> "$rc"
          info "Appended mirror env to $rc"
        fi
        return 0
      fi
    done
  fi
}

write_flashcli_mirror_env() {
  mirror_mode_enabled || return 0
  _home="$(flashcli_home_path)"
  mkdir -p "$_home"
  {
    printf '%s\n' "FLASHCLI_USE_MIRROR=1"
    printf 'PIP_INDEX_URL=%s\n' "${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
    printf 'PIP_TRUSTED_HOST=%s\n' "${PIP_TRUSTED_HOST:-$MIRROR_PIP_TRUSTED_HOST}"
    printf 'HF_ENDPOINT=%s\n' "${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
    printf '%s\n' "FLASHCLI_PREFER_HF_MIRROR=1"
    printf 'FLASHCLI_GIT_PROXY=%s\n' "${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}"
  } > "${_home}/mirror.env"
  info "Wrote ${_home}/mirror.env (flashcli run pip/HF/GitHub downloads will use mirrors)"
}

write_flashcli_install_env() {
  _home="$(flashcli_home_path)"
  mkdir -p "$_home"
  {
    printf 'FLASHCLI_INSTALL_REPO=%s\n' "$REPO"
    printf 'FLASHCLI_INSTALL_REF=%s\n' "$REF"
  } > "${_home}/install.env"
  info "Wrote ${_home}/install.env (git source for flashcli-bundle in bundle venvs)"
}

# Keep a local copy at $FLASHCLI_HOME/install.sh for re-runs after curl|sh installs.
persist_install_script() {
  _home="$(flashcli_home_path)"
  _dest="${_home}/install.sh"
  mkdir -p "$_home"

  # Already running from the persisted path.
  case "$0" in
    "$_dest")
      [ -x "$_dest" ] || chmod +x "$_dest" 2>/dev/null || true
      return 0
      ;;
  esac

  # Local file invocation: copy self.
  if [ -f "$0" ] && [ -r "$0" ] && [ "$0" != "sh" ] && [ "$0" != "-sh" ] && [ "$0" != "/bin/sh" ]; then
    if cp "$0" "$_dest" 2>/dev/null; then
      chmod +x "$_dest" 2>/dev/null || true
      info "Wrote ${_dest} (re-run: ${_dest} --mirror)"
      return 0
    fi
  fi

  # Piped install (curl|sh): re-fetch from the same channel as this install.
  _url="https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh"
  if mirror_mode_enabled; then
    _url="https://gitee.com/aodiansoft/flashcli/raw/main/install.sh"
  fi
  case "${REPO:-}" in
    *gitee.com*) _url="https://gitee.com/aodiansoft/flashcli/raw/main/install.sh" ;;
  esac

  _tmp="${_dest}.tmp.$$"
  if command -v curl >/dev/null 2>&1; then
    if curl -fsSL --connect-timeout 8 --max-time 60 -o "$_tmp" "$_url" 2>/dev/null; then
      mv -f "$_tmp" "$_dest"
      chmod +x "$_dest" 2>/dev/null || true
      info "Wrote ${_dest} (re-run: ${_dest} --mirror)"
      return 0
    fi
  elif command -v wget >/dev/null 2>&1; then
    if wget -q --timeout=60 -O "$_tmp" "$_url" 2>/dev/null; then
      mv -f "$_tmp" "$_dest"
      chmod +x "$_dest" 2>/dev/null || true
      info "Wrote ${_dest} (re-run: ${_dest} --mirror)"
      return 0
    fi
  fi
  rm -f "$_tmp" 2>/dev/null || true
  return 0
}

# Verify flashcli works in parent shell (minimal PATH / no /usr/local/bin is common in containers).
verify_cli_usable() {
  cli="$(flashcli_script_path || true)"
  [ -n "$cli" ] || die "flashcli console script missing after install"

  cli_dir="$(dirname "$cli")"

  if ! flashcli_script_is_runnable "$cli"; then
    die "flashcli --help failed: $cli"
  fi

  ensure_global_cli_wrappers || true
  for _path_dir in /usr/local/bin /usr/bin "$cli_dir"; do
    prepend_path_dir "$_path_dir"
  done
  hash -r 2>/dev/null || true

  persist_path_config "$cli_dir"
  write_flashcli_mirror_env
  write_flashcli_install_env
  persist_install_script

  resolved="$(command -v flashcli 2>/dev/null || true)"
  if [ -z "$resolved" ]; then
    for _candidate in /usr/local/bin/flashcli /usr/bin/flashcli "$cli"; do
      if flashcli_script_is_runnable "$_candidate"; then
        resolved="$_candidate"
        prepend_path_dir "$(dirname "$_candidate")"
        hash -r 2>/dev/null || true
        break
      fi
    done
  fi

  if [ -z "$resolved" ]; then
    die "flashcli not found on PATH after install.
Reason: CLI wrappers could not be placed on PATH (check permissions).
Installed at: $cli
Fix: export PATH=\"${cli_dir}:\$PATH\" && hash -r"
  fi

  if ! flashcli_script_is_runnable "$resolved"; then
    die "flashcli --help failed for resolved command: $resolved"
  fi

  info "[ok] flashcli on PATH: $resolved"

  if [ "$PIP_INSTALL_USER" = "0" ]; then
    case "$resolved" in
      "${HOME:-}/.local/bin/"*)
        die "system install expected but flashcli resolves to user site ($resolved). Run: pip uninstall -y flashcli && ./install.sh"
        ;;
    esac
  fi
}

# Optional post-install pytest (requires git clone of source tree; tests are not in the wheel).
run_post_install_tests() {
  if [ "$RUN_TESTS" != "1" ] && [ "$RUN_CORE_TESTS" != "1" ]; then
    return 0
  fi
  have_cmd git || die "post-install tests require git (clone ${REPO} @ ${REF})"

  _home="$(flashcli_home_path)"
  _src="${_home}/test-src"
  info "Post-install tests: preparing source checkout at ${_src} ..."

  if [ -d "${_src}/.git" ]; then
    git -C "${_src}" fetch --depth 1 origin "${REF}" >/dev/null 2>&1 \
      || git -C "${_src}" fetch --depth 1 "${REPO}" "${REF}" >/dev/null 2>&1 \
      || true
    git -C "${_src}" checkout "${REF}" >/dev/null 2>&1 \
      || git -C "${_src}" checkout FETCH_HEAD >/dev/null 2>&1 \
      || die "cannot checkout ${REF} in ${_src}"
  else
    rm -rf "${_src}" 2>/dev/null || true
    if GIT_TERMINAL_PROMPT=0 git -c credential.helper= \
      clone --depth 1 --branch "${REF}" "${REPO}" "${_src}" >/dev/null 2>&1; then
      :
    elif GIT_TERMINAL_PROMPT=0 git -c credential.helper= \
      clone --depth 1 "${REPO}" "${_src}" >/dev/null 2>&1; then
      GIT_TERMINAL_PROMPT=0 git -c credential.helper= -C "${_src}" \
        fetch --depth 1 origin "${REF}" >/dev/null 2>&1 \
        || GIT_TERMINAL_PROMPT=0 git -c credential.helper= -C "${_src}" \
          fetch --depth 1 "${REPO}" "${REF}" >/dev/null 2>&1 \
        || die "git fetch ${REF} failed for post-install tests"
      git -C "${_src}" checkout FETCH_HEAD >/dev/null 2>&1 \
        || die "git checkout ${REF} failed for post-install tests"
    else
      die "git clone ${REPO} failed (needed for post-install tests)"
    fi
  fi

  [ -d "${_src}/tests" ] || die "tests/ missing in ${_src} — wrong ref or incomplete clone?"
  [ -f "${_src}/pyproject.toml" ] || die "pyproject.toml missing in ${_src}"

  info "Installing pytest and editable flashcli for test run ..."
  do_pip_install --upgrade pytest \
    || die "cannot install pytest for post-install tests"
  do_pip_install --upgrade -e "${_src}/flashcli-bundle[infer]" \
    || die "editable flashcli-bundle[infer] install failed for post-install tests"
  do_pip_install --upgrade --force-reinstall --no-deps -e "${_src}" \
    || die "editable flashcli install failed for post-install tests"

  _core_tests="
    tests/test_preset_ref.py
    tests/test_reexec_argv.py
    tests/test_flashcli_bundle_infer.py
    tests/test_deps_imports_ok.py
    tests/test_cli_errors.py
    tests/test_infer_cli.py
    tests/test_version.py
    tests/test_hf_hub.py
    tests/test_preset_validate.py
    tests/test_deps_flashcli_bundle.py
  "

  if [ "$RUN_TESTS" = "1" ]; then
    info "Running full pytest suite under ${_src}/tests ..."
    if ! (
      cd "${_src}"
      unset HF_ENDPOINT FLASHCLI_USE_MIRROR FLASHCLI_PREFER_HF_MIRROR \
        FLASHCLI_PREFER_GITHUB_MIRROR FLASHCLI_GIT_PROXY PIP_INDEX_URL PIP_TRUSTED_HOST \
        2>/dev/null || true
      export FLASHCLI_NO_MIRROR=1
      run_py -m pytest tests -q --tb=line --ignore=tests/bench
    ); then
      die "post-install pytest failed (full suite). Re-run: cd ${_src} && pytest tests/"
    fi
  else
    info "Running core pytest subset ..."
    if ! (
      cd "${_src}"
      unset HF_ENDPOINT FLASHCLI_USE_MIRROR FLASHCLI_PREFER_HF_MIRROR \
        FLASHCLI_PREFER_GITHUB_MIRROR FLASHCLI_GIT_PROXY PIP_INDEX_URL PIP_TRUSTED_HOST \
        2>/dev/null || true
      export FLASHCLI_NO_MIRROR=1
      # shellcheck disable=SC2086
      run_py -m pytest ${_core_tests} -q --tb=line
    ); then
      die "post-install pytest failed (core subset). Re-run with --run-tests for full suite."
    fi
  fi
  info "[ok] post-install tests passed"
}

print_success() {
  [ "$QUIET" = "1" ] && return 0
  printf '\n%s\n' 'flashcli installed successfully.'
  if should_use_venv && [ -n "${VIRTUAL_ENV:-}" ]; then
    printf '%s\n' "  (venv: ${VIRTUAL_ENV})"
    _venv_bin="${VIRTUAL_ENV}/bin"
    if ! path_has_dir "$_venv_bin"; then
      printf '%s\n' "  export PATH=\"${_venv_bin}:\$PATH\"   # activate venv CLI in this shell"
    fi
  fi
  if mirror_mode_enabled; then
    printf '%s\n' "  (mirror: PyPI=${MIRROR_PIP_LABEL:-tuna}, HF/git + get-pip; ref=${REF})"
    if os_mirror_enabled && [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
      printf '%s\n' "  (mirror: apt/yum/dnf/apk → mirrors.aliyun.com when applicable)"
    fi
  elif [ -n "${PIP_MIRROR_CHOICE:-}" ]; then
    printf '%s\n' "  (pip mirror: ${MIRROR_PIP_LABEL:-tuna}; ref=${REF})"
  fi
  printf '%s\n' "  (source: ${REPO} @ ${REF})"
  printf '%s\n' '' 'Next steps:'
  printf '%s\n' '  flashcli doctor'
  printf '%s\n' '  flashcli models envs flashcli-bundle/pi05_libero:1.0.4'
  if ! mirror_mode_enabled; then
    printf '%s\n' '  # slow network: ./install.sh --mirror'
    printf '%s\n' '  # alternate git:  ./install.sh --repo https://gitee.com/org/flashcli.git'
  fi
  printf '%s\n' '  flashcli pull flashcli-bundle/pi05_libero:1.0.4'
  printf '%s\n' '  flashcli run flashcli-bundle/pi05_libero:1.0.4 --image /path/to.jpg --prompt "pick up the block"'
  _fc="$(command -v flashcli 2>/dev/null || true)"
  if [ -z "$_fc" ]; then
    if [ -x /usr/bin/flashcli ]; then
      printf '%s\n' '  export PATH="/usr/bin:$PATH"   # if flashcli not found'
    elif [ -x /usr/local/bin/flashcli ]; then
      printf '%s\n' '  export PATH="/usr/local/bin:$PATH"'
    fi
    printf '%s\n' '  hash -r'
  else
    printf '%s\n' "  # flashcli → ${_fc}"
    printf '%s\n' '  hash -r   # if command not found in this shell'
  fi
  if [ -f /etc/profile.d/flashcli.sh ]; then
    printf '%s\n' '  source /etc/profile.d/flashcli.sh   # login shells'
  fi
  printf '%s\n' '' "Docs: https://github.com/aodianyun/flashcli"
}

main() {
  # Before any git/pip work: never block on Username for public clone (see configure_*).
  configure_noninteractive_git
  parse_args "$@"
  apply_mirror_endpoints
  run_preflight
  export FLASHCLI_INSTALL_REPO="$REPO"
  export FLASHCLI_INSTALL_REF="$REF"
  export FLASHCLI_USE_MIRROR="$USE_MIRROR"
  export FLASHCLI_PIP_MIRROR="${PIP_MIRROR_CHOICE:-}"
  export FLASHCLI_PIP_MIRROR_PROBE="${PIP_MIRROR_PROBE}"
  export FLASHCLI_REQUIRES_PYTHON_MIN="$REQUIRES_PYTHON_MIN"
  install_flashcli
  verify_and_repair_pyproject
  verify_cli_usable
  run_post_install_tests
  print_success
}

main "$@"
