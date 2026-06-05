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
#   FLASHCLI_OS_MIRROR=0    With --mirror, skip rewriting OS package-manager sources
#   FLASHCLI_GIT_PROXY=URL   Opt-in GitHub fetch proxy (e.g. https://mirror.ghproxy.com/)
#   FLASHCLI_GIT_TIMEOUT=25  Timeout (seconds) for git ls-remote during preflight
#   FLASHCLI_PYTHON
#   FLASHCLI_SKIP_GPU_CHECK=1   skip GPU probe (default: warn if missing, still install)
#   FLASHCLI_REQUIRE_GPU=1      abort install when no NVIDIA GPU (default: install CLI anyway)
#   FLASHCLI_SKIP_ENV_CHECK=1
#   FLASHCLI_PIP_USER=auto|0|1
#   FLASHCLI_QUIET=1
#   FLASHCLI_NO_REPAIR=1          skip one automatic pip repair retry
#   FLASHCLI_STRICT_PIP_CHECK=1   fail on any pip check conflict (default: flashcli-only)
#   FLASHCLI_AUTO_INSTALL_PYTHON=0  disable auto OS install of python3+pip+git (default: on when root)
#   FLASHCLI_BREAK_SYSTEM_PACKAGES=1  pass pip --break-system-packages (PEP 668 images)
#   FLASHCLI_USE_VENV=0             skip venv; install to system/user site (default: ~/.flashcli/venv)

set -eu

DEFAULT_REPO_GITHUB="https://github.com/aodianyun/flashcli.git"
DEFAULT_REPO_GITEE="https://gitee.com/aodiansoft/flashcli.git"
DEFAULT_REPO="$DEFAULT_REPO_GITHUB"
REPO="${FLASHCLI_INSTALL_REPO:-$DEFAULT_REPO}"
REF="${FLASHCLI_INSTALL_REF:-main}"
QUIET="${FLASHCLI_QUIET:-0}"
USE_MIRROR="${FLASHCLI_USE_MIRROR:-0}"
REPO_FROM_USER=0
if [ -n "${FLASHCLI_INSTALL_REPO:-}" ]; then
  REPO_FROM_USER=1
fi

# Alternate endpoints when --mirror / FLASHCLI_USE_MIRROR=1
MIRROR_PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
MIRROR_PIP_TRUSTED_HOST="mirrors.aliyun.com"
MIRROR_HF_ENDPOINT="https://hf-mirror.com"
MIRROR_GET_PIP_URL="https://mirrors.aliyun.com/pypi/get-pip/get-pip.py"
DEFAULT_GIT_PROXY_PREFIX="https://mirror.ghproxy.com/"
OS_MIRRORS_APPLIED=0

# ---------------------------------------------------------------------------
# pyproject.toml [project] — keep in sync with repo pyproject.toml
# ---------------------------------------------------------------------------
REQUIRES_PYTHON_MIN="3.10"
MIN_PIP_VERSION="21.3"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
PYPROJECT_DEPS="typer>=0.12 pyyaml>=6.0 packaging>=23.0 huggingface_hub>=0.26 tqdm>=4.66 fastapi>=0.100 'uvicorn[standard]>=0.24'"
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
  --mirror                  Use China-friendly mirrors (pip/HF/git; root: apt/yum/dnf/apk too)
  --global, --no-mirror     Disable mirror endpoints (force direct official endpoints)
  --gitee                   Shortcut: --repo https://gitee.com/aodiansoft/flashcli.git
  --github                  Shortcut: --repo https://github.com/aodianyun/flashcli.git

Environment (override flags):
  FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF
  FLASHCLI_USE_MIRROR=1
  FLASHCLI_OS_MIRROR=0      With --mirror, do not rewrite apt/yum/dnf/apk sources
  FLASHCLI_GIT_PROXY=URL    Opt-in GitHub proxy (default --mirror uses Gitee for official repo)
  FLASHCLI_GIT_TIMEOUT=25   git ls-remote timeout during preflight (seconds)
  FLASHCLI_AUTO_INSTALL_PYTHON=0  Disable auto OS install of python3+pip (default: on for root)
  FLASHCLI_USE_VENV=0             Install to system/user site instead of ~/.flashcli/venv (default: venv)
  FLASHCLI_REQUIRE_GPU=1          Abort when no NVIDIA GPU (default: warn and continue)
  FLASHCLI_SKIP_GPU_CHECK=1       Skip GPU probe entirely
  PIP_INDEX_URL, HF_ENDPOINT  Override mirror defaults

Examples:
  curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
  curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
  ./install.sh --mirror
  ./install.sh --global
  ./install.sh --ref develop
  ./install.sh --mirror --ref main
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
  if mirror_mode_enabled && [ -z "${GET_PIP_URL_OVERRIDE:-}" ]; then
    printf '%s\n' "$MIRROR_GET_PIP_URL"
  else
    printf '%s\n' "${GET_PIP_URL_OVERRIDE:-$GET_PIP_URL}"
  fi
}

# Best-effort rewrite of OS package sources to Aliyun (root, Linux). Idempotent.
apply_apt_mirror() {
  have_cmd apt-get || return 0
  have_cmd sed || return 0
  if grep -rq 'mirrors.aliyun.com' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    return 0
  fi
  info "[i] mirror: switching apt sources → mirrors.aliyun.com (backup: sources.list.flashcli-bak)"
  if [ -f /etc/apt/sources.list ] && [ ! -f /etc/apt/sources.list.flashcli-bak ]; then
    cp -a /etc/apt/sources.list /etc/apt/sources.list.flashcli-bak 2>/dev/null || true
  fi
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$f" ] || continue
    sed -i \
      -e 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|https://archive.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|http://security.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|https://security.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|http://ports.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|https://ports.ubuntu.com|https://mirrors.aliyun.com|g' \
      -e 's|http://deb.debian.org|https://mirrors.aliyun.com|g' \
      -e 's|https://deb.debian.org|https://mirrors.aliyun.com|g' \
      -e 's|http://security.debian.org|https://mirrors.aliyun.com|g' \
      -e 's|https://security.debian.org|https://mirrors.aliyun.com|g' \
      "$f" 2>/dev/null || true
  done
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

# Apply mirror endpoints unless the user already exported overrides.
apply_mirror_endpoints() {
  mirror_mode_enabled || return 0

  if [ -z "${PIP_INDEX_URL:-}" ]; then
    export PIP_INDEX_URL="$MIRROR_PIP_INDEX_URL"
    export PIP_TRUSTED_HOST="$MIRROR_PIP_TRUSTED_HOST"
  fi
  if [ -z "${HF_ENDPOINT:-}" ]; then
    export HF_ENDPOINT="$MIRROR_HF_ENDPOINT"
  fi
  if [ -z "${FLASHCLI_PREFER_HF_MIRROR:-}" ]; then
    export FLASHCLI_PREFER_HF_MIRROR=1
  fi

  maybe_apply_default_git_proxy
  apply_os_package_mirrors

  if [ -z "${PIP_DEFAULT_TIMEOUT:-}" ]; then
    export PIP_DEFAULT_TIMEOUT=120
  fi

  info "[i] mirror: PIP_INDEX_URL=${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
  info "[i] mirror: HF_ENDPOINT=${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
  info "[i] mirror: get-pip → $(get_pip_bootstrap_url)"
}

# When --mirror is on: official repo → Gitee; other GitHub URLs → direct unless FLASHCLI_GIT_PROXY set.
maybe_apply_default_git_proxy() {
  mirror_mode_enabled || return 0
  [ "$REPO_FROM_USER" -eq 1 ] && return 0

  if [ "$REPO" = "$DEFAULT_REPO_GITHUB" ]; then
    REPO="$DEFAULT_REPO_GITEE"
    info "[i] mirror: git clone via Gitee ($REPO); pass --github to keep GitHub"
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

# Run git with a network timeout so preflight cannot hang silently on dead proxies.
run_git_timeout() {
  _secs="${FLASHCLI_GIT_TIMEOUT:-25}"
  if have_cmd timeout; then
    timeout "$_secs" git "$@"
    return $?
  fi
  git -c http.lowSpeedLimit=1000 -c "http.lowSpeedTime=${_secs}" "$@"
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

pip_extra_flags() {
  if should_break_system_packages; then
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

flashcli_venv_path() {
  printf '%s' "${FLASHCLI_VENV:-${HOME:-/root}/.flashcli/venv}"
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
  if have_cmd apt-get; then
    apt-get update -qq && apt-get install -y python3 python3-pip python3-venv git zip rsync \
      && return 0
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

# pip install with PEP 668 / old pip fallbacks. Streams to stderr unless --quiet.
do_pip_install() {
  _log="/tmp/flashcli-pip-$$.log"
  _break="$(pip_extra_flags || true)"
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
    set -- --root-user-action=ignore "$@"
  fi
  _run_pip() {
    if [ "$QUIET" = "1" ]; then
      run_py -m pip install "$@" >"$_log" 2>&1
    elif have_cmd tee; then
      run_py -m pip install "$@" 2>&1 | tee "$_log" >&2
    else
      run_py -m pip install "$@" >"$_log" 2>&1
      cat "$_log" >&2
    fi
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
    if should_break_system_packages; then
      warn "PEP 668 — retrying pip with --break-system-packages"
      if run_py -m pip install --break-system-packages "$@" >"$_log" 2>&1; then
        [ "$QUIET" = "1" ] || cat "$_log" >&2
        rm -f "$_log"
        return 0
      fi
    fi
  fi
  cat "$_log" >&2
  rm -f "$_log"
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
      "$_base" -m pip install virtualenv >/dev/null 2>&1 \
        || "$_base" -m pip install --break-system-packages virtualenv >/dev/null 2>&1 \
        || return 1
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
try_pip3_same_interpreter() {
  if ! have_cmd pip3; then
    return 1
  fi
  _pip3_py="$(pip3 -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
  if [ -n "$_pip3_py" ] && [ "$_pip3_py" = "$PYTHON" ]; then
    pip3 install --upgrade pip >/dev/null 2>&1 || true
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

ensure_pip() {
  export FLASHCLI_MIN_PIP_VERSION="$MIN_PIP_VERSION"

  if pip_works; then
    if pip_version_ok; then
      info "[ok] pip: $(run_py -m pip --version 2>/dev/null | head -n 1)"
      return 0
    fi
    warn "pip is older than ${MIN_PIP_VERSION}; upgrading ..."
    do_pip_install --upgrade "pip>=${MIN_PIP_VERSION}" \
      || do_pip_install --upgrade pip \
      || warn "pip upgrade failed; continuing with existing pip"
    if pip_works && pip_version_ok; then
      info "[ok] pip upgraded: $(run_py -m pip --version 2>/dev/null | head -n 1)"
      return 0
    fi
  fi

  info "pip module missing — trying ensurepip ..."
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    run_py -m ensurepip --upgrade --user >/dev/null 2>&1 \
      || run_py -m ensurepip --user >/dev/null 2>&1 \
      || true
  else
    run_py -m ensurepip --upgrade >/dev/null 2>&1 \
      || run_py -m ensurepip >/dev/null 2>&1 \
      || true
  fi
  if pip_works; then
    info "[ok] pip via ensurepip: $(run_py -m pip --version 2>/dev/null | head -n 1)"
    return 0
  fi

  try_pip3_same_interpreter && info "[ok] pip via pip3" && return 0

  if try_os_install_pip; then
    if [ -z "${VIRTUAL_ENV:-}" ] && PYTHON="$(discover_python)"; then
      export PYTHON
    fi
    if pip_works; then
      info "[ok] pip via OS package manager ($PYTHON)"
      return 0
    fi
  fi

  if bootstrap_pip_get_pip; then
    info "[ok] pip via get-pip.py: $(run_py -m pip --version 2>/dev/null | head -n 1)"
    return 0
  fi

  if ensure_flashcli_venv; then
    if pip_works; then
      info "[ok] pip: $(run_py -m pip --version 2>/dev/null | head -n 1)"
      return 0
    fi
  fi

  die "cannot bootstrap pip for $PYTHON.
Reason: pip/ensurepip/get-pip and OS package install all failed.
This host may mix interpreters (e.g. Debian /usr/bin/python3.13 + /usr/local python3.12).
Fix:
  FLASHCLI_PYTHON=\$(command -v python3) ./install.sh
  apt install -y python3-pip python3-venv   # Debian/Ubuntu (root)
  ./install.sh --mirror                      # slow/blocked network
  FLASHCLI_BREAK_SYSTEM_PACKAGES=1 ./install.sh"
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
Reason: pip/network/permissions failed (venv avoids most PEP 668 issues).
Fix: ./install.sh --mirror   or   check errors above"
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
  apply_os_package_mirrors
  if have_cmd apt-get; then
    info "Installing OS packages via apt: $*"
    apt-get update -qq && apt-get install -y "$@" && return 0
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
  ensure_host_tool zip zip
  ensure_host_tool rsync rsync
}

check_network() {
  if ! have_cmd git; then
    return 0
  fi
  info "Checking git remote (${FLASHCLI_GIT_TIMEOUT:-25}s timeout): $REPO @ $REF"
  if git_ref_reachable "$REPO" "$REF"; then
    info "[ok] git remote reachable: $REPO ($REF)"
    return 0
  fi
  warn "cannot verify git remote (timeout/offline/firewall?) — pip clone may still fail"
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
  ensure_home
  if [ "${FLASHCLI_SKIP_ENV_CHECK:-0}" = "1" ]; then
    warn "FLASHCLI_SKIP_ENV_CHECK=1: minimal pre-flight only"
    resolve_python
    ensure_minimal_base_pip || true
    ensure_flashcli_venv || true
    set_pip_install_mode
    ensure_pip
    ensure_packaging
    return 0
  fi
  check_os
  check_gpu
  warn_python2_only
  resolve_python
  ensure_minimal_base_pip || true
  ensure_flashcli_venv || true
  set_pip_install_mode
  check_python_version
  ensure_pip
  ensure_packaging
  preflight_pyproject
  ensure_build_deps
  ensure_git
  ensure_zip_rsync
  check_network
  check_install_target
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
  spec="git+${REPO}@${REF}"
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    info "Installing $spec → $(pip_scripts_dir 1) (pip --user; may take a few minutes) ..."
  elif [ -n "${VIRTUAL_ENV:-}" ]; then
    info "Installing $spec → $(pip_scripts_dir 0) (venv; may take a few minutes) ..."
  else
    cleanup_stale_user_install
    info "Installing $spec → $(pip_scripts_dir 0) (system site; may take a few minutes) ..."
  fi

  if _pip_install_flashcli_spec "$spec"; then
    info "[ok] pip install finished"
    return 0
  fi

  if try_mirror_repo_fallback; then
    spec="git+${REPO}@${REF}"
    info "Retrying install: $spec"
    if _pip_install_flashcli_spec "$spec"; then
      info "[ok] pip install finished (mirror fallback)"
      return 0
    fi
  fi

  die "pip install failed for git+${REPO}@${REF}.
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
  export FLASHCLI_PYPROJECT_DEPS="$PYPROJECT_DEPS"

  if "$PYTHON" - <<'PY'
import os
import subprocess
import sys

REPAIR = os.environ.get("FLASHCLI_NO_REPAIR", "0") != "1"
PIP_USER = os.environ.get("FLASHCLI_PIP_INSTALL_USER") == "1"
IMPORT_NAMES = {"pyyaml": "yaml", "huggingface-hub": "huggingface_hub"}
CANONICAL_DEPS = os.environ.get("FLASHCLI_PYPROJECT_DEPS", "").split()


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
    found = {
        ep.name
        for ep in entry_points(group="console_scripts")
        if ep.name in ("flashcli", "flash") and ep.value == expected
    }
    missing = {"flashcli", "flash"} - found
    if missing:
        err(f"[project.scripts] missing: {', '.join(sorted(missing))}")

    try:
        from flashcli.cli import app  # noqa: F401
    except Exception as exc:
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
    # Re-install canonical [project] deps from embedded list + flashcli
    specs = []
    for s in CANONICAL_DEPS:
        if not s:
            continue
        if s.startswith("packaging"):
            specs.append(packaging_spec_for_env())
        else:
            specs.append(s)
    if sys.version_info < (3, 11):
        specs.append("tomli>=2.0")
    repo = os.environ.get("FLASHCLI_INSTALL_REPO", "")
    ref = os.environ.get("FLASHCLI_INSTALL_REF", "main")
    specs.append(f"git+{repo}@{ref}")
    print("[info] attempting automatic repair (pip install deps + flashcli) ...", file=sys.stderr)
    pip_install(*specs)


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
    print(f"error:   {sys.executable} -m pip install --force-reinstall 'git+{repo}@{ref}'", file=sys.stderr)
    print(f"error:   {sys.executable} -m pip install {' '.join(CANONICAL_DEPS)}", file=sys.stderr)
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
flashcli_script_path() {
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    for d in "$(pip_scripts_dir 1)" "${HOME:-}/.local/bin"; do
      [ -n "$d" ] && [ -x "${d}/flashcli" ] && printf '%s' "${d}/flashcli" && return 0
    done
    return 1
  fi
  for d in "$(pip_scripts_dir 0)" "/usr/local/bin" "/usr/bin"; do
    [ -n "$d" ] && [ -x "${d}/flashcli" ] && printf '%s' "${d}/flashcli" && return 0
  done
  return 1
}

link_cli_into_system_bin() {
  [ "$PIP_INSTALL_USER" = "0" ] || return 0
  system_bin="$(pip_scripts_dir 0)"
  [ -n "$system_bin" ] || system_bin="/usr/local/bin"
  cli="$(flashcli_script_path || true)"
  [ -n "$cli" ] || return 0
  [ "$(dirname "$cli")" = "$system_bin" ] && return 0
  mkdir -p "$system_bin" 2>/dev/null || die "cannot create $system_bin"
  info "Linking flashcli → ${system_bin}/flashcli"
  ln -sf "$cli" "${system_bin}/flashcli"
  ln -sf "$cli" "${system_bin}/flash" 2>/dev/null || true
  _link_hub_cli_from_dir "$system_bin" "$(dirname "$cli")"
}

_link_hub_cli_from_dir() {
  _dest="$1"
  _src_dir="$2"
  for _name in hf huggingface-cli; do
    if [ -x "${_src_dir}/${_name}" ]; then
      ln -sf "${_src_dir}/${_name}" "${_dest}/${_name}" 2>/dev/null || true
    fi
  done
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

# Minimal PATH images often omit /usr/local/bin — mirror CLI into /usr/bin when needed.
mirror_cli_to_usr_bin() {
  cli="$1"
  cli_dir="$(dirname "$cli")"
  [ "$cli_dir" != "/usr/bin" ] || return 0
  [ -d /usr/bin ] || return 0
  if path_has_dir /usr/bin; then
    if [ ! -e /usr/bin/flashcli ] || [ -L /usr/bin/flashcli ]; then
      info "Linking flashcli → /usr/bin/flashcli (current PATH lacks ${cli_dir})"
      ln -sf "$cli" /usr/bin/flashcli
      ln -sf "$cli" /usr/bin/flash 2>/dev/null || true
      _link_hub_cli_from_dir /usr/bin "$cli_dir"
    fi
  fi
}

write_flashcli_mirror_env() {
  mirror_mode_enabled || return 0
  _home="${FLASHCLI_HOME:-${HOME:-/root}/.flashcli}"
  mkdir -p "$_home"
  {
    printf '%s\n' "FLASHCLI_USE_MIRROR=1"
    printf 'PIP_INDEX_URL=%s\n' "${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
    printf 'PIP_TRUSTED_HOST=%s\n' "${PIP_TRUSTED_HOST:-$MIRROR_PIP_TRUSTED_HOST}"
    printf 'HF_ENDPOINT=%s\n' "${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
    printf '%s\n' "FLASHCLI_PREFER_HF_MIRROR=1"
  } > "${_home}/mirror.env"
  info "Wrote ${_home}/mirror.env (flashcli run pip/HF will use mirrors)"
}

# Verify flashcli works in parent shell (minimal PATH / no /usr/local/bin is common in containers).
verify_cli_usable() {
  link_cli_into_system_bin
  cli="$(flashcli_script_path || true)"
  [ -n "$cli" ] || die "flashcli console script missing after install"

  cli_dir="$(dirname "$cli")"

  if ! "$cli" --help >/dev/null 2>&1; then
    die "flashcli --help failed: $cli"
  fi

  if ! path_has_dir "$cli_dir"; then
    mirror_cli_to_usr_bin "$cli"
    persist_path_config "$cli_dir"
  else
    persist_path_config "$cli_dir"
  fi
  write_flashcli_mirror_env

  # Prefer: current PATH → cli_dir first → common system paths
  resolved=""
  for try_path in \
    "${PATH:-}" \
    "${cli_dir}:${PATH:-}" \
    "${cli_dir}:/usr/local/bin:/usr/bin:/bin" \
    "/usr/bin:/bin"; do
    [ -n "$try_path" ] || continue
    resolved="$(env PATH="$try_path" command -v flashcli 2>/dev/null || true)"
    if [ -n "$resolved" ]; then
      break
    fi
  done

  if [ -z "$resolved" ]; then
    if [ -x /usr/bin/flashcli ]; then
      resolved="/usr/bin/flashcli"
    elif [ -x "$cli" ]; then
      resolved="$cli"
      warn "flashcli is at $cli but not on PATH — run: export PATH=\"${cli_dir}:\$PATH\" && hash -r"
      info "[ok] flashcli installed: $cli"
      return 0
    fi
    die "flashcli not found on PATH. Installed at: $cli — run: export PATH=\"${cli_dir}:\$PATH\" && hash -r"
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
    printf '%s\n' "  (mirror: pip/HF/git + get-pip; ref=${REF})"
    if os_mirror_enabled && [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
      printf '%s\n' "  (mirror: apt/yum/dnf/apk → mirrors.aliyun.com when applicable)"
    fi
  fi
  printf '%s\n' "  (source: ${REPO} @ ${REF})"
  printf '%s\n' '' 'Next steps:'
  printf '%s\n' '  flashcli doctor'
  printf '%s\n' '  flashcli models envs pi05_libero'
  if ! mirror_mode_enabled; then
    printf '%s\n' '  # slow network: ./install.sh --mirror'
    printf '%s\n' '  # alternate git:  ./install.sh --repo https://gitee.com/org/flashcli.git'
  fi
  printf '%s\n' '  flashcli pull pi05_libero'
  printf '%s\n' '  flashcli run pi05_libero --image /path/to.jpg --prompt "pick up the block"'
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
  parse_args "$@"
  apply_mirror_endpoints
  run_preflight
  export FLASHCLI_INSTALL_REPO="$REPO"
  export FLASHCLI_INSTALL_REF="$REF"
  export FLASHCLI_USE_MIRROR="$USE_MIRROR"
  export FLASHCLI_REQUIRES_PYTHON_MIN="$REQUIRES_PYTHON_MIN"
  install_flashcli
  verify_and_repair_pyproject
  verify_cli_usable
  print_success
}

main "$@"
