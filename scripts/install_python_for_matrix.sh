#!/usr/bin/env bash
# Install Python 3.10 / 3.11 / 3.12 for pi05 release matrix builds.
#
# Methods (use --method auto by default):
#   apt         — Debian/Ubuntu packages (3.12 often missing)
#   deadsnakes  — Ubuntu only: PPA for 3.11/3.12
#   standalone  — Download Astral python-build-standalone (works in K8s/Debian without 3.12 apt)
#   auto        — apt, then standalone for anything still missing
#
# Usage:
#   sudo bash scripts/install_python_for_matrix.sh
#   sudo bash scripts/install_python_for_matrix.sh --minors 311,312
#   sudo bash scripts/install_python_for_matrix.sh --method standalone --minors 311,312
#
# After install, source the env file before building:
#   source ~/.flashcli/python-matrix.env
#   bash scripts/build_release_matrix.sh --bundle pi05_libero --cuda-tag 124
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_ROOT="${FLASHCLI_PYTHON_ROOT:-/opt/flashcli-python}"
ENV_FILE="${FLASHCLI_PYTHON_ENV:-/root/.flashcli/python-matrix.env}"
METHOD="auto"
MINORS="310,311,312"
STANDALONE_TAG="${FLASHCLI_PYTHON_STANDALONE_TAG:-20241206}"

# cpython M.m+pbs tag → install_only tarball (linux x86_64)
standalone_url() {
  local mm="$1"  # 3.12
  local tag="$2"
  local base="https://github.com/astral-sh/python-build-standalone/releases/download/${tag}"
  case "${mm}" in
    3.10) echo "${base}/cpython-3.10.16%2B${tag}-x86_64-unknown-linux-gnu-install_only.tar.gz" ;;
    3.11) echo "${base}/cpython-3.11.11%2B${tag}-x86_64-unknown-linux-gnu-install_only.tar.gz" ;;
    3.12) echo "${base}/cpython-3.12.8%2B${tag}-x86_64-unknown-linux-gnu-install_only.tar.gz" ;;
    *) die "No standalone URL for Python ${mm}" ;;
  esac
}

log() { printf '[install-python] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Install Python interpreters for build_release_matrix.sh / release_bundle.sh.

Usage:
  sudo bash scripts/install_python_for_matrix.sh [OPTIONS]

Options:
  --method METHOD     auto | apt | deadsnakes | standalone (default: auto)
  --minors LIST       Comma-separated: 310,311,312 (default: all three)
  --python-root DIR   Standalone install prefix (default: ${PYTHON_ROOT})
  --env-file PATH     Write FLASHCLI_PY*_BIN here (default: ${ENV_FILE})
  --standalone-tag TAG  python-build-standalone release (default: ${STANDALONE_TAG})
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --method) METHOD="$2"; shift 2 ;;
    --minors) MINORS="$2"; shift 2 ;;
    --python-root) PYTHON_ROOT="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --standalone-tag) STANDALONE_TAG="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

IFS=',' read -r -a MINOR_LIST <<< "${MINORS}"

py_minor_tag() { echo "$1"; }  # 310
py_mm_version() {
  local py="$1"
  echo "${py:0:1}.${py:1:2}"
}

resolve_bin() {
  local py="$1"
  local mm want_maj want_min var override
  mm="$(py_mm_version "${py}")"
  want_maj="${py:0:1}"
  want_min="${py:1:2}"
  var="FLASHCLI_PY${py}_BIN"
  override="${!var:-}"
  local ver="python${mm}"
  local c resolved=""
  for c in \
    "${override}" \
    "${ver}" \
    "/usr/local/bin/${ver}" \
    "/usr/bin/${ver}" \
    "${PYTHON_ROOT}/${mm}/bin/${ver}" \
    "${PYTHON_ROOT}/${mm}/bin/python3"; do
    [[ -n "${c}" ]] || continue
    if command -v "${c}" >/dev/null 2>&1; then
      resolved="$(command -v "${c}")"
    elif [[ -x "${c}" ]]; then
      resolved="${c}"
    else
      continue
    fi
    if "${resolved}" -c "import sys; exit(0 if sys.version_info[:2]==(${want_maj}, ${want_min}) else 1)" 2>/dev/null; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done
  return 1
}

apt_pkg_available() {
  local pkg="$1"
  apt-cache show "${pkg}" 2>/dev/null | grep -q "^Package: ${pkg}$"
}

install_apt_minor() {
  local py="$1"
  local mm
  mm="$(py_mm_version "${py}")"
  local ver="python${mm}"
  if resolve_bin "${py}" >/dev/null 2>&1; then
    log "py${py}: already $(resolve_bin "${py}")"
    return 0
  fi
  if ! apt_pkg_available "${ver}"; then
    return 1
  fi
  local pkgs=("${ver}")
  apt_pkg_available "${ver}-dev" && pkgs+=("${ver}-dev")
  log "py${py}: apt install ${pkgs[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
  resolve_bin "${py}" >/dev/null 2>&1
}

install_deadsnakes() {
  if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    log "deadsnakes: skipped (not Ubuntu)"
    return 1
  fi
  apt-get update -qq
  apt-get install -y --no-install-recommends software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  local py mm ver pkgs=()
  for py in "${MINOR_LIST[@]}"; do
    resolve_bin "${py}" >/dev/null 2>&1 && continue
    mm="$(py_mm_version "${py}")"
    ver="python${mm}"
    apt_pkg_available "${ver}" && pkgs+=("${ver}" "${ver}-venv")
    apt_pkg_available "${ver}-dev" && pkgs+=("${ver}-dev")
  done
  [[ ${#pkgs[@]} -gt 0 ]] || return 0
  log "deadsnakes: apt install ${pkgs[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
}

install_standalone_minor() {
  local py="$1"
  local mm dest tarball url pybin
  mm="$(py_mm_version "${py}")"
  if resolve_bin "${py}" >/dev/null 2>&1; then
    log "py${py}: already $(resolve_bin "${py}")"
    return 0
  fi
  dest="${PYTHON_ROOT}/${mm}"
  mkdir -p "${PYTHON_ROOT}"
  url="$(standalone_url "${mm}" "${STANDALONE_TAG}")"
  tarball="${PYTHON_ROOT}/.cache/cpython-${mm}-${STANDALONE_TAG}.tar.gz"
  mkdir -p "${PYTHON_ROOT}/.cache"
  if [[ ! -f "${tarball}" ]]; then
    log "py${py}: downloading standalone ${mm} (${STANDALONE_TAG})"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "${tarball}" "${url}"
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "${tarball}" "${url}"
    else
      die "Need curl or wget to download standalone Python"
    fi
  fi
  rm -rf "${dest}"
  mkdir -p "${dest}"
  tar -xzf "${tarball}" -C "${dest}" --strip-components=1
  pybin="${dest}/bin/python3"
  [[ -x "${pybin}" ]] || pybin="${dest}/bin/python${mm}"
  [[ -x "${pybin}" ]] || die "Standalone extract failed under ${dest}/bin"
  if ! "${pybin}" -c "import sys; assert sys.version_info[:2]==(${py:0:1}, ${py:1:2})" 2>/dev/null; then
    die "${pybin} is not Python ${mm}"
  fi
  ln -sf "${pybin}" "${dest}/bin/python${mm}"
  log "py${py}: standalone -> ${pybin}"
}

write_env_file() {
  mkdir -p "$(dirname "${ENV_FILE}")"
  {
    echo "# Generated by install_python_for_matrix.sh — source before matrix build"
    echo "#   source ${ENV_FILE}"
    local py bin var
    for py in "${MINOR_LIST[@]}"; do
      py="${py// /}"
      [[ -n "${py}" ]] || continue
      if bin="$(resolve_bin "${py}" 2>/dev/null)"; then
        var="FLASHCLI_PY${py}_BIN"
        echo "export ${var}=${bin}"
      fi
    done
  } > "${ENV_FILE}"
  log "Wrote ${ENV_FILE}"
  cat "${ENV_FILE}" >&2
}

run_auto() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    local py
    for py in "${MINOR_LIST[@]}"; do
      py="${py// /}"
      install_apt_minor "${py}" || true
    done
    install_deadsnakes || true
  fi
  local py
  for py in "${MINOR_LIST[@]}"; do
    py="${py// /}"
    resolve_bin "${py}" >/dev/null 2>&1 && continue
    install_standalone_minor "${py}"
  done
}

main() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "Run as root (sudo) for apt/standalone install under ${PYTHON_ROOT}"
  fi
  case "${METHOD}" in
    apt)
      apt-get update -qq
      for py in "${MINOR_LIST[@]}"; do install_apt_minor "${py// /}" || die "apt failed for py${py}"; done
      ;;
    deadsnakes) install_deadsnakes ;;
    standalone)
      for py in "${MINOR_LIST[@]}"; do install_standalone_minor "${py// /}"; done
      ;;
    auto) run_auto ;;
    *) die "Unknown --method ${METHOD}" ;;
  esac

  local missing=()
  for py in "${MINOR_LIST[@]}"; do
    py="${py// /}"
    resolve_bin "${py}" >/dev/null 2>&1 || missing+=("py${py}")
  done
  [[ ${#missing[@]} -eq 0 ]] || die "Still missing: ${missing[*]}"

  write_env_file
  local bundle="${RELEASE_BUNDLE_NAME:-<bundle>}"
  log "Ready. Example next step:"
  log "  source ${ENV_FILE} && bash scripts/release_bundle.sh --bundle ${bundle}"
}

main "$@"
