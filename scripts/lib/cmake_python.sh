# CMake FindPython3 hints for pybind / FlashRT native builds.
#
#   source scripts/lib/cmake_python.sh
#   local -a args=()
#   cmake_append_python3_args args "${PYTHON_BIN}"

cmake_python_include_dir() {
  local py_bin="$1"
  "${py_bin}" -c 'import sysconfig; print(sysconfig.get_path("include"))' 2>/dev/null
}

cmake_python_library_path() {
  local py_bin="$1"
  "${py_bin}" <<'PY'
import os
import sysconfig

libdir = sysconfig.get_config_var("LIBDIR") or ""
for name in (
    sysconfig.get_config_var("INSTSONAME"),
    sysconfig.get_config_var("LDLIBRARY"),
    sysconfig.get_config_var("LIBRARY"),
):
    if not name:
        continue
    path = name if os.path.isabs(name) else os.path.join(libdir, name)
    if os.path.isfile(path):
        print(path)
        break
PY
}

ensure_python_dev_headers() {
  local py_bin="$1"
  local include mm ver dev_pkg
  [[ -n "${py_bin}" && -x "${py_bin}" ]] || return 1

  include="$(cmake_python_include_dir "${py_bin}")"
  if [[ -n "${include}" && -f "${include}/Python.h" ]]; then
    return 0
  fi

  mm="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || return 1
  ver="python${mm}"
  dev_pkg="${ver}-dev"

  if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
    if declare -f log >/dev/null 2>&1; then
      log "Installing ${dev_pkg} for CMake Development headers"
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${dev_pkg}" >/dev/null 2>&1 || true
  fi

  include="$(cmake_python_include_dir "${py_bin}")"
  [[ -n "${include}" && -f "${include}/Python.h" ]]
}

cmake_append_python3_args() {
  # Usage: local -a args=(); cmake_append_python3_args args "${PYTHON_BIN}"
  local -n _out="$1"
  local py_bin="$2"
  [[ -n "${py_bin}" && -x "${py_bin}" ]] || return 1

  ensure_python_dev_headers "${py_bin}" || {
    local include
    include="$(cmake_python_include_dir "${py_bin}")"
    if declare -f die >/dev/null 2>&1; then
      die "Python development headers missing (${include:-?}/Python.h). Install python*-dev for ${py_bin}"
    fi
    return 1
  }

  local prefix include lib
  prefix="$("${py_bin}" -c 'import sysconfig; print(sysconfig.get_config_var("prefix") or sys.prefix)' 2>/dev/null)"
  include="$(cmake_python_include_dir "${py_bin}")"
  lib="$(cmake_python_library_path "${py_bin}")"

  _out+=(-DPython3_EXECUTABLE="${py_bin}")
  _out+=(-DPython3_ROOT_DIR="${prefix}")
  _out+=(-DPython3_INCLUDE_DIR="${include}")
  if [[ -n "${lib}" && -f "${lib}" ]]; then
    _out+=(-DPython3_LIBRARY="${lib}")
  fi
  _out+=(-DPython3_FIND_STRATEGY=LOCATION)
  _out+=(-DPython3_FIND_REGISTRY=NEVER)
}
