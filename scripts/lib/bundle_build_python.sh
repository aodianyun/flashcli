# Resolve / auto-install Python for bundle native builds (cmake + pybind).
#
# Reads python_abi from flashcli-bundle.json (fallback: release-matrix.env).
# Reuses scripts/lib/matrix_python.sh + install_python_for_matrix.sh.
#
# Globals (set by caller): PYTHON_BIN, PYTHON_MINOR, AUTO_INSTALL_BUILD_PYTHON
#
#   source scripts/lib/bundle_build_python.sh
#   bundle_build_python_prepare "${BUNDLE_DIR}" "${FLASHCLI_ROOT}"

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=matrix_python.sh
source "${_LIB_DIR}/matrix_python.sh"

bundle_manifest_python_abi() {
  local bundle_dir="$1"
  local manifest="${bundle_dir}/flashcli-bundle.json"
  [[ -f "${manifest}" ]] || return 1
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import json; print(json.load(open('${manifest}'))['python_abi'])" 2>/dev/null && return 0
  fi
  local abi
  abi="$(sed -n 's/.*"python_abi"[[:space:]]*:[[:space:]]*"\([0-9][0-9][0-9]\)".*/\1/p' "${manifest}" | head -1)"
  [[ -n "${abi}" ]] || return 1
  printf '%s\n' "${abi}"
}

bundle_build_python_load_env() {
  local f
  for f in \
    "${FLASHCLI_PYTHON_ENV:-}" \
    "${HOME}/.flashcli/python-matrix.env" \
    "${HOME}/.flashcli/python-runtime.env"; do
    [[ -n "${f}" && -f "${f}" ]] || continue
    # shellcheck source=/dev/null
    source "${f}"
  done
}

bundle_build_python_auto_install_enabled() {
  case "${FLASHCLI_AUTO_INSTALL_BUILD_PYTHON:-${AUTO_INSTALL_BUILD_PYTHON:-1}}" in
    0|false|no|off) return 1 ;;
    *) return 0 ;;
  esac
}

bundle_build_python_prepare() {
  local bundle_dir="$1" flashcli_root="$2"
  bundle_build_python_load_env

  if [[ -z "${PYTHON_MINOR}" ]]; then
    PYTHON_MINOR="$(bundle_manifest_python_abi "${bundle_dir}")" || true
    if [[ -z "${PYTHON_MINOR}" ]]; then
      local env_file="${bundle_dir}/release-matrix.env"
      if [[ -f "${env_file}" ]]; then
        # shellcheck source=/dev/null
        source "${env_file}"
        PYTHON_MINOR="${RELEASE_PYTHON_ABI:-}"
      fi
    fi
    [[ -n "${PYTHON_MINOR}" ]] || {
      if declare -f die >/dev/null 2>&1; then
        die "Could not read python_abi from ${bundle_dir}/flashcli-bundle.json"
      fi
      return 1
    }
  fi

  if [[ -n "${PYTHON_BIN}" ]]; then
    if ! python_bin_reports_minor "${PYTHON_BIN}" "${PYTHON_MINOR}"; then
      if declare -f die >/dev/null 2>&1; then
        die "--python-bin ${PYTHON_BIN} is not Python ${PYTHON_MINOR:0:1}.${PYTHON_MINOR:1:2} (manifest py${PYTHON_MINOR})"
      fi
      return 1
    fi
    if declare -f log >/dev/null 2>&1; then
      log "Using --python-bin ${PYTHON_BIN} (py${PYTHON_MINOR})"
    fi
    return 0
  fi

  if resolved="$(resolve_python_bin "${PYTHON_MINOR}" 2>/dev/null)"; then
    PYTHON_BIN="${resolved}"
    # shellcheck source=cmake_python.sh
    source "${_LIB_DIR}/cmake_python.sh"
    ensure_python_dev_headers "${PYTHON_BIN}" || {
      if declare -f log >/dev/null 2>&1; then
        log "Python py${PYTHON_MINOR} found at ${PYTHON_BIN} but dev headers missing; will try install"
      fi
      resolved=""
    }
    if [[ -n "${resolved}" ]]; then
      if declare -f log >/dev/null 2>&1; then
        log "Found Python py${PYTHON_MINOR}: ${PYTHON_BIN}"
      fi
      return 0
    fi
  fi

  if ! bundle_build_python_auto_install_enabled; then
    if declare -f die >/dev/null 2>&1; then
      die "Python py${PYTHON_MINOR} not found. Set FLASHCLI_PY${PYTHON_MINOR}_BIN or omit --no-install-python to auto-install"
    fi
    return 1
  fi

  if declare -f log >/dev/null 2>&1; then
    log "Python py${PYTHON_MINOR} not found; auto-installing (FLASHCLI_AUTO_INSTALL_BUILD_PYTHON=0 or --no-install-python to disable)"
  fi

  if [[ -z "${FLASHCLI_PYTHON_ROOT:-}" && "$(id -u)" -ne 0 ]]; then
    export FLASHCLI_PYTHON_ROOT="${HOME}/.flashcli/python"
  fi
  if [[ -z "${FLASHCLI_PYTHON_ENV:-}" ]]; then
    export FLASHCLI_PYTHON_ENV="${HOME}/.flashcli/python-matrix.env"
  fi

  local method="${FLASHCLI_BUILD_PYTHON_METHOD:-standalone}"
  install_python_matrix "${flashcli_root}" "${PYTHON_MINOR}" "${PYTHON_MINOR}" "${method}"
  PYTHON_BIN="$(python_bin_for_minor "${PYTHON_MINOR}")"

  # shellcheck source=cmake_python.sh
  source "${_LIB_DIR}/cmake_python.sh"
  ensure_python_dev_headers "${PYTHON_BIN}" || {
    if declare -f die >/dev/null 2>&1; then
      die "Python py${PYTHON_MINOR} at ${PYTHON_BIN} is missing development headers (python*-dev)"
    fi
    return 1
  }

  if declare -f log >/dev/null 2>&1; then
    log "Using Python py${PYTHON_MINOR}: ${PYTHON_BIN}"
  fi
}
