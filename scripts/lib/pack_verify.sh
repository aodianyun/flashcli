# Matrix + ABI verification before packing lib/*.so
# Requires: log, die, probe_native_so_python_abi, verify_native_matrix_multi

pack_verify_lib_matrix_and_abi() {
  local bundle_dir="$1" sm="$2" cuda_tags="$3" os_name="$4" arch="$5" py_minors="$6"
  local native_lib="${bundle_dir}/lib"
  [[ -d "${native_lib}" ]] || {
    die "Missing ${native_lib}"
    return 1
  }

  verify_native_matrix_multi "${native_lib}" "${sm}" "${cuda_tags}" "${os_name}" "${arch}" \
    "${py_minors}" flash_rt_kernels flash_rt_fa2 \
    || die "lib/ matrix incomplete (expected sm${sm} × cu${cuda_tags} × py${py_minors})"

  local py major minor ver py_bin override var cuda py_mod pattern so rc err
  for py in ${py_minors}; do
    major="${py:0:1}"
    minor="${py:1:2}"
    ver="python${major}.${minor}"
    py_bin=""
    var="FLASHCLI_PY${py}_BIN"
    override="${!var:-}"
    if [[ -n "${override}" && -x "${override}" ]]; then
      py_bin="${override}"
    elif command -v "${ver}" >/dev/null 2>&1; then
      py_bin="$(command -v "${ver}")"
    elif command -v python3 >/dev/null 2>&1; then
      local got
      got="$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor:02d}")' 2>/dev/null || true)"
      [[ "${got}" == "${py}" ]] && py_bin="$(command -v python3)"
    fi
    if [[ -z "${py_bin}" ]]; then
      log "WARN: skip ABI probe for py${py} (no ${ver}; set FLASHCLI_PY${py}_BIN)"
      continue
    fi
    for cuda in ${cuda_tags}; do
      for py_mod in flash_rt_kernels flash_rt_fa2; do
        pattern="${native_lib}/${py_mod}*-sm${sm}-cu${cuda}-${os_name}-${arch}-py${py}.so"
        shopt -s nullglob
        local -a matches=( ${pattern} )
        shopt -u nullglob
        [[ ${#matches[@]} -ge 1 ]] || continue
        so="${matches[0]}"
        rc=0
        err="$(probe_native_so_python_abi "${py_bin}" "${so}" 2>&1)" || rc=$?
        if [[ "${rc}" -eq 2 ]]; then
          die "ABI mismatch: ${so} does not load under ${py_bin}: ${err}"
        fi
        if [[ "${rc}" -eq 0 ]]; then
          log "ABI OK: $(basename "${so}") under ${py_bin}"
        else
          log "WARN: $(basename "${so}") probe rc=${rc} under ${py_bin}"
        fi
      done
    done
  done
}
