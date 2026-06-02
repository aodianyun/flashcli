# Python interpreter resolution for release matrix builds.
# Source after defining log/die (optional):
#   source scripts/lib/matrix_python.sh

python_candidates_for_minor() {
  local py="$1"
  local major="${py:0:1}" minor="${py:1:2}"
  local ver="python${major}.${minor}"
  local var="FLASHCLI_PY${py}_BIN"
  local override="${!var:-}"
  local root="${FLASHCLI_PYTHON_ROOT:-/opt/flashcli-python}"
  if [[ -n "${override}" ]]; then
    printf '%s\n' "${override}"
    return
  fi
  printf '%s\n' \
    "${ver}" \
    "/usr/local/bin/${ver}" \
    "/usr/bin/${ver}" \
    "${root}/${major}.${minor}/bin/${ver}" \
    "${root}/${major}.${minor}/bin/python3" \
    "/opt/python/${ver}/bin/${ver}"
}

python_bin_reports_minor() {
  local bin="$1" py="$2"
  local want_major="${py:0:1}" want_minor="${py:1:2}"
  [[ -x "${bin}" ]] || return 1
  local got_major got_minor
  got_major="$("${bin}" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)" || return 1
  got_minor="$("${bin}" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)" || return 1
  [[ "${got_major}" == "${want_major}" && "${got_minor}" == "${want_minor}" ]]
}

resolve_python_bin() {
  local py="$1"
  local candidate resolved=""
  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    if command -v "${candidate}" >/dev/null 2>&1; then
      resolved="$(command -v "${candidate}")"
    elif [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    else
      continue
    fi
    if python_bin_reports_minor "${resolved}" "${py}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done < <(python_candidates_for_minor "${py}")
  return 1
}

python_bin_for_minor() {
  resolve_python_bin "$1" || {
    if declare -f die >/dev/null 2>&1; then
      die "No Python ${1:0:1}.${1:1:2} found (py${1}). Set FLASHCLI_PY${1}_BIN=/path/to/python"
    fi
    return 1
  }
}

install_python_matrix() {
  local flashcli_root="$1" py_minors_csv="$2" only_py="${3:-}" method="${4:-auto}"
  local install_sh="${flashcli_root}/scripts/install_python_for_matrix.sh"
  [[ -f "${install_sh}" ]] || {
    die "Missing ${install_sh}"
    return 1
  }
  local minors=() py
  for py in ${py_minors_csv}; do
    [[ -z "${only_py}" || "${only_py}" == "${py}" ]] || continue
    minors+=("${py}")
  done
  local minors_csv
  minors_csv="$(IFS=,; echo "${minors[*]}")"
  log "Running install_python_for_matrix.sh --method ${method} --minors ${minors_csv}"
  bash "${install_sh}" --method "${method}" --minors "${minors_csv}"
  local env_file="${FLASHCLI_PYTHON_ENV:-/root/.flashcli/python-matrix.env}"
  if [[ -f "${env_file}" ]]; then
    # shellcheck source=/dev/null
    source "${env_file}"
    log "Loaded ${env_file}"
  fi
}

ensure_python_matrix() {
  local flashcli_root="$1" py_minors_csv="$2" only_py="${3:-}" install="${4:-0}" method="${5:-auto}"
  local missing=() py
  for py in ${py_minors_csv}; do
    [[ -z "${only_py}" || "${only_py}" == "${py}" ]] || continue
    resolve_python_bin "${py}" >/dev/null 2>&1 || missing+=("py${py}")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ "${install}" -eq 1 ]]; then
    install_python_matrix "${flashcli_root}" "${py_minors_csv}" "${only_py}" "${method}"
    missing=()
    for py in ${py_minors_csv}; do
      [[ -z "${only_py}" || "${only_py}" == "${py}" ]] || continue
      resolve_python_bin "${py}" >/dev/null 2>&1 || missing+=("py${py}")
    done
    [[ ${#missing[@]} -eq 0 ]] && return 0
  fi
  die "Missing Python: ${missing[*]}. Set FLASHCLI_PY*_BIN or pass --install-python"
}
