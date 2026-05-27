#!/bin/sh
# flashcli installer — curl -fsSL …/install.sh | sh
#
# Goals:
#   1. Pre-flight: make the host as ready as possible for pyproject.toml [project]
#   2. Install flashcli (+ deps incl. huggingface_hub → hf CLI) for root/venv/user
#   3. Post-flight: verify imports, flashcli/hf on PATH, pip check; auto-repair once
#   4. Exit 1 with actionable errors if requirements still cannot be met
#
# Optional env:
#   FLASHCLI_INSTALL_REPO / FLASHCLI_INSTALL_REF   (default: main @ GitHub)
#   FLASHCLI_USE_MIRROR=1   Aliyun PyPI + hf-mirror for pip/HF (optional GitHub fetch proxy)
#   FLASHCLI_GIT_PROXY=0|URL   disable or override default GitHub proxy when using --mirror
#   FLASHCLI_PYTHON
#   FLASHCLI_SKIP_GPU_CHECK=1
#   FLASHCLI_SKIP_ENV_CHECK=1
#   FLASHCLI_PIP_USER=auto|0|1
#   FLASHCLI_QUIET=1
#   FLASHCLI_NO_REPAIR=1          skip one automatic pip repair retry
#   FLASHCLI_AUTO_INSTALL_PYTHON=1  (root) try apt/dnf/apk to install python3+pip+git
#   FLASHCLI_BREAK_SYSTEM_PACKAGES=1  pass pip --break-system-packages (PEP 668 images)
#   FLASHCLI_USE_VENV=1             install into ~/.flashcli/venv (bypass PEP 668)
#
# Examples:
#   curl -fsSL …/install.sh | sh
#   curl -fsSL …/install.sh | sh -s -- --ref feature/foo
#   curl -fsSL …/install.sh | sh -s -- --mirror
#   curl -fsSL …/install.sh | sh -s -- --repo https://gitee.com/org/flashcli.git --ref main

set -eu

DEFAULT_REPO="https://github.com/aodianyun/flashcli.git"
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
DEFAULT_GIT_PROXY_PREFIX="https://mirror.ghproxy.com/"

# ---------------------------------------------------------------------------
# pyproject.toml [project] — keep in sync with repo pyproject.toml
# ---------------------------------------------------------------------------
REQUIRES_PYTHON_MIN="3.10"
MIN_PIP_VERSION="21.3"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
PYPROJECT_DEPS="typer>=0.12 pyyaml>=6.0 packaging>=23.0 huggingface_hub>=0.26 tqdm>=4.66"
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
  curl -fsSL …/install.sh | sh -s -- [OPTIONS]

Options:
  -h, --help              Show this help
  -q, --quiet             Less output
  --ref REF, --branch REF   Git ref (branch/tag/commit). Default: main
  --repo URL, --git-url URL Git remote for pip install (GitHub, Gitee, self-hosted, …)
  --mirror                  Use alternate PyPI + Hugging Face Hub mirrors for install

Environment (override flags):
  FLASHCLI_INSTALL_REPO, FLASHCLI_INSTALL_REF
  FLASHCLI_USE_MIRROR=1
  FLASHCLI_GIT_PROXY=0      Disable GitHub fetch proxy when --mirror + default repo
  PIP_INDEX_URL, HF_ENDPOINT  Override mirror defaults

Examples:
  ./install.sh
  ./install.sh --ref develop
  ./install.sh --mirror --ref v0.2.0
  ./install.sh --repo https://gitee.com/your-org/flashcli.git --ref main
  FLASHCLI_USE_MIRROR=1 ./install.sh --repo https://gitee.com/your-org/flashcli.git
EOF
}

mirror_mode_enabled() {
  case "${USE_MIRROR}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
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

  info "[i] mirror: PIP_INDEX_URL=${PIP_INDEX_URL:-$MIRROR_PIP_INDEX_URL}"
  info "[i] mirror: HF_ENDPOINT=${HF_ENDPOINT:-$MIRROR_HF_ENDPOINT}"
}

# When --mirror is on and repo is still the default GitHub URL, optionally prefix a fetch proxy.
maybe_apply_default_git_proxy() {
  mirror_mode_enabled || return 0
  [ "$REPO_FROM_USER" -eq 1 ] && return 0
  case "${FLASHCLI_GIT_PROXY:-auto}" in
    0|false|no|off) return 0 ;;
  esac
  case "$REPO" in
    https://github.com/*) ;;
    *) return 0 ;;
  esac
  _proxy="${FLASHCLI_GIT_PROXY:-$DEFAULT_GIT_PROXY_PREFIX}"
  case "$_proxy" in
    auto) _proxy="$DEFAULT_GIT_PROXY_PREFIX" ;;
  esac
  _proxy="${_proxy%/}/"
  REPO="${_proxy}${REPO}"
  info "[i] mirror: git fetch via ${REPO}"
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
  printf '%s\n' "error: no Python >= ${REQUIRES_PYTHON_MIN} found on this system." >&2
  printf '%s\n' "error: searched: ${PYTHON_CANDIDATES:-python3}" >&2
  printf '%s\n' "error:" >&2
  printf '%s\n' "error: Install Python 3.10+ and pip, then re-run. Examples:" >&2
  printf '%s\n' "error:   Debian/Ubuntu: apt install -y python3 python3-pip python3-venv git" >&2
  printf '%s\n' "error:   RHEL/Fedora:   dnf install -y python3 python3-pip git" >&2
  printf '%s\n' "error:   Alpine:        apk add python3 py3-pip git" >&2
  printf '%s\n' "error: Or set: FLASHCLI_PYTHON=/usr/bin/python3.12" >&2
  printf '%s\n' "error: Optional (root): FLASHCLI_AUTO_INSTALL_PYTHON=1 ./install.sh" >&2
  exit 1
}

try_auto_install_python() {
  if [ "${FLASHCLI_AUTO_INSTALL_PYTHON:-0}" != "1" ]; then
    return 1
  fi
  if [ "$(id -u 2>/dev/null || echo 1)" -ne 0 ]; then
    warn "FLASHCLI_AUTO_INSTALL_PYTHON=1 requires root; skipping OS package install"
    return 1
  fi
  info "Attempting OS package install for python3 + pip + git (FLASHCLI_AUTO_INSTALL_PYTHON=1) ..."
  if have_cmd apt-get; then
    apt-get update -qq && apt-get install -y python3 python3-pip python3-venv git \
      && return 0
  fi
  if have_cmd dnf; then
    dnf install -y python3 python3-pip git && return 0
  fi
  if have_cmd yum; then
    yum install -y python3 python3-pip git && return 0
  fi
  if have_cmd apk; then
    apk add --no-cache python3 py3-pip git && return 0
  fi
  if have_cmd zypper; then
    zypper --non-interactive install python3 python3-pip git && return 0
  fi
  return 1
}

resolve_python() {
  if PYTHON="$(discover_python)"; then
    export PYTHON
    return 0
  fi
  if try_auto_install_python; then
    PYTHON="$(discover_python)" && export PYTHON && return 0
  fi
  die_no_python
}

# Run Python (honours PYTHONNOUSERSITE when set).
run_py() {
  "$PYTHON" "$@"
}

# pip install with PEP 668 / old pip fallbacks.
do_pip_install() {
  _log="/tmp/flashcli-pip-$$.log"
  _break="$(pip_extra_flags || true)"
  if [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]; then
    set -- --root-user-action=ignore "$@"
  fi
  if [ -n "$_break" ]; then
    if run_py -m pip install $_break "$@" >"$_log" 2>&1; then
      [ "$QUIET" = "1" ] || cat "$_log" >&2
      rm -f "$_log"
      return 0
    fi
  elif run_py -m pip install "$@" >"$_log" 2>&1; then
    [ "$QUIET" = "1" ] || cat "$_log" >&2
    rm -f "$_log"
    return 0
  fi
  if grep -qi 'externally-managed-environment' "$_log" 2>/dev/null; then
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

try_apt_python3_pip() {
  [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ] || return 1
  have_cmd apt-get || return 1
  info "Installing python3-pip via apt (Debian/Ubuntu) ..."
  apt-get update -qq && apt-get install -y python3-pip python3-venv \
    && return 0
  return 1
}

bootstrap_pip_get_pip() {
  if ! have_cmd curl && ! have_cmd wget; then
    return 1
  fi
  _tmp="$(mktemp /tmp/get-pip.XXXXXX.py)"
  if have_cmd curl; then
    curl -fsSL "$GET_PIP_URL" -o "$_tmp" || return 1
  else
    wget -qO "$_tmp" "$GET_PIP_URL" || return 1
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

# Dedicated venv when system Python is PEP 668 and pip cannot be bootstrapped in-place.
ensure_flashcli_venv() {
  _venv="${FLASHCLI_VENV:-${HOME:-/root}/.flashcli/venv}"
  case "${FLASHCLI_USE_VENV:-auto}" in
    0 | false | no) return 1 ;;
  esac
  if [ "${FLASHCLI_USE_VENV:-auto}" != "1" ] && [ "${FLASHCLI_USE_VENV:-auto}" != "true" ]; then
    # auto: only when PEP 668 and pip still missing
    python_is_pep668 "$PYTHON" 2>/dev/null || return 1
    pip_works && return 1
  fi
  info "Creating virtualenv at $_venv (PEP 668 / FLASHCLI_USE_VENV) ..."
  run_py -m venv "$_venv" 2>/dev/null \
    || run_py -m virtualenv "$_venv" 2>/dev/null \
    || die "cannot create venv at $_venv — install python3-venv"
  PYTHON="${_venv}/bin/python3"
  if [ ! -x "$PYTHON" ]; then
    PYTHON="${_venv}/bin/python"
  fi
  export PYTHON VIRTUAL_ENV="$_venv"
  PIP_INSTALL_USER=0
  FLASHCLI_PIP_USER_FLAG=""
  unset PYTHONNOUSERSITE
  export PIP_INSTALL_USER FLASHCLI_PIP_INSTALL_USER=0
  pip_works || die "venv created but pip missing in $_venv"
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
    die "nvidia-smi not found — flashcli inference needs an NVIDIA GPU on Linux"
  fi
  gpu_line="$(nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  [ -n "$gpu_line" ] || die "nvidia-smi present but no GPU reported"
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

  if try_apt_python3_pip; then
    if PYTHON="$(discover_python)"; then
      export PYTHON
    fi
    if pip_works; then
      info "[ok] pip via apt python3-pip ($PYTHON)"
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

This host mixes interpreters (e.g. Debian /usr/bin/python3.13 + /usr/local python3.12).
Try:
  FLASHCLI_PYTHON=\$(command -v python3) ./install.sh
  apt install -y python3-pip python3-venv   # Debian/Ubuntu
  FLASHCLI_USE_VENV=1 ./install.sh
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
    || die "cannot install packaging>=23.0 — check network, permissions, or PEP 668 (try FLASHCLI_BREAK_SYSTEM_PACKAGES=1)"
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
    || die "cannot install build dependencies (setuptools, wheel)"
}

check_git() {
  have_cmd git || die "git not found — required for: pip install git+${REPO}"
  info "[ok] git: $(git --version 2>/dev/null | head -n 1)"
}

check_network() {
  if ! have_cmd git; then
    return 0
  fi
  if git ls-remote --heads "$REPO" "$REF" >/dev/null 2>&1; then
    info "[ok] git remote reachable: $REPO ($REF)"
    return 0
  fi
  warn "cannot verify git remote (offline/firewall?) — pip clone may still fail"
}

check_install_target() {
  "$PYTHON" - <<'PY' || die "install target not writable (permissions?)"
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
  if [ "${FLASHCLI_SKIP_ENV_CHECK:-0}" = "1" ]; then
    warn "FLASHCLI_SKIP_ENV_CHECK=1: minimal pre-flight only"
    resolve_python
    set_pip_install_mode
    ensure_pip
    ensure_packaging
    return 0
  fi
  check_os
  check_gpu
  warn_python2_only
  resolve_python
  set_pip_install_mode
  check_python_version
  ensure_pip
  ensure_packaging
  preflight_pyproject
  ensure_build_deps
  check_git
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

install_flashcli() {
  spec="git+${REPO}@${REF}"
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    info "Installing $spec → $(pip_scripts_dir 1) (pip --user)"
  else
    cleanup_stale_user_install
    info "Installing $spec → $(pip_scripts_dir 0) (system site)"
  fi

  set -- --upgrade --force-reinstall
  if [ "$PIP_INSTALL_USER" = "1" ]; then
    set -- "$@" --user
  fi
  [ "$QUIET" = "1" ] && set -- "$@" -q
  set -- "$@" "$spec"

  if ! do_pip_install "$@"; then
    die "pip install failed for $spec — check git/network/disk and errors above"
  fi
  info "[ok] pip install finished"
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

    chk = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    if chk.returncode != 0:
        err(f"pip check:\n{(chk.stdout or '') + (chk.stderr or '')}".strip())

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
    specs = [s for s in CANONICAL_DEPS if s]
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
  fi

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
  if mirror_mode_enabled; then
    printf '%s\n' "  (mirror endpoints: ref=${REF})"
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
