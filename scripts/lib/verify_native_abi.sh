# Verify lib/*.so Python ABI tags with matrix interpreters (FLASHCLI_PY*_BIN).
#
# Requires:
#   probe_native_so_python_abi  (scripts/lib/probe_native_abi.sh)
#   python_bin_for_minor        (scripts/lib/matrix_python.sh)
#   log / die                   (caller)
#
#   verify_native_lib_python_abi BUNDLE_DIR SM CUDA_TAGS OS ARCH PY_MINORS [STRICT_MISSING]
#     STRICT_MISSING=1 (default) — die if an interpreter is missing
#     STRICT_MISSING=0           — warn and skip (host pack fallback)

verify_native_lib_python_abi() {
  local bundle_dir="$1" sm="$2" cuda_tags="$3" os_name="$4" arch="$5" py_minors="$6"
  local strict_missing="${7:-1}"
  local native_lib="${bundle_dir}/lib"
  local py cuda py_mod pattern so rc err py_bin probe_env
  local -a py_mods=()
  if [[ -n "${RELEASE_NATIVE_MODULES:-}" ]]; then
    read -r -a py_mods <<< "${RELEASE_NATIVE_MODULES}"
  fi

  [[ -d "${native_lib}" ]] || {
    die "Missing ${native_lib}"
    return 1
  }

  probe_env=()
  if [[ -n "${CUDA_HOME:-}" ]]; then
    local cuda_lib=""
    for cuda_lib in "${CUDA_HOME}/lib64" "${CUDA_HOME}/lib" "${CUDA_HOME}/targets/x86_64-linux/lib"; do
      [[ -d "${cuda_lib}" ]] || continue
      probe_env+=( "LD_LIBRARY_PATH=${cuda_lib}:${LD_LIBRARY_PATH:-}" )
      break
    done
  fi

  for py in ${py_minors}; do
    py_bin=""
    if declare -f python_bin_for_minor >/dev/null 2>&1; then
      py_bin="$(python_bin_for_minor "${py}")" || py_bin=""
    fi
    if [[ -z "${py_bin}" ]]; then
      if [[ "${strict_missing}" -eq 1 ]]; then
        die "No Python ${py:0:1}.${py:1:2} for ABI verify (set FLASHCLI_PY${py}_BIN or pass --install-python)"
      fi
      log "WARN: skip ABI probe for py${py} (no interpreter; set FLASHCLI_PY${py}_BIN)"
      continue
    fi
    for cuda in ${cuda_tags}; do
      shopt -s nullglob
      if [[ ${#py_mods[@]} -eq 0 ]]; then
        local -a matches=( "${native_lib}"/*-sm${sm}-cu${cuda}-${os_name}-${arch}-py${py}.so )
      else
        local -a matches=()
        for py_mod in "${py_mods[@]}"; do
          pattern="${native_lib}/${py_mod}*-sm${sm}-cu${cuda}-${os_name}-${arch}-py${py}.so"
          local -a mod_matches=( ${pattern} )
          matches+=( "${mod_matches[@]}" )
        done
      fi
      shopt -u nullglob
      for so in "${matches[@]}"; do
        [[ -f "${so}" ]] || continue
        rc=0
        err=""
        if [[ ${#probe_env[@]} -gt 0 ]]; then
          err="$(env "${probe_env[@]}" probe_native_so_python_abi "${py_bin}" "${so}" 2>&1)" || rc=$?
        else
          err="$(probe_native_so_python_abi "${py_bin}" "${so}" 2>&1)" || rc=$?
        fi
        if [[ "${rc}" -eq 2 ]]; then
          die "ABI mismatch: $(basename "${so}") does not load under ${py_bin}: ${err}"
        fi
        if [[ "${rc}" -eq 0 ]]; then
          log "ABI OK: $(basename "${so}") under ${py_bin}"
        else
          log "WARN: $(basename "${so}") probe rc=${rc} under ${py_bin}${err:+: ${err}}"
        fi
      done
    done
  done
}
