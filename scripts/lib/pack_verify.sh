# Matrix + ABI verification before packing lib/*.so or manifest-declared runtime dirs.
# Requires: log, die, verify_native_matrix_multi, verify_native_lib_python_abi

pack_verify_runtime_matrix() {
  local bundle_dir="$1" sm="$2" cuda_tags="$3" os_name="$4" arch="$5" py_minors="$6"
  local -a modules=()
  if [[ -n "${RELEASE_NATIVE_MODULES:-}" ]]; then
    read -r -a modules <<< "${RELEASE_NATIVE_MODULES}"
  fi
  local manifest="${bundle_dir}/flashcli-bundle.json"
  local -A rel_by_env=()
  if [[ -f "${manifest}" ]]; then
    while IFS=$'\t' read -r key rel; do
      [[ -n "${key}" ]] && rel_by_env["${key}"]="${rel}"
    done < <(python3 - "${manifest}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
runtime = data.get("runtime")
if not isinstance(runtime, dict):
    runtime = {}
    for key, block in (data.get("environments") or {}).items():
        if isinstance(block, dict):
            runtime[key] = block.get("runtime", "")
for key, rel in runtime.items():
    print(f"{key}\t{rel or ''}")
PY
)
  fi

  local cuda py env_key rel cell_dir mod pattern
  local -a matches=()
  for cuda in ${cuda_tags}; do
    for py in ${py_minors}; do
      env_key="$(runtime_env_key "${sm}" "${cuda}" "${os_name}" "${arch}" "${py}")"
      rel="runtime/${env_key}"
      if [[ -n "${rel_by_env[${env_key}]+x}" ]]; then
        rel="${rel_by_env[${env_key}]}"
      fi
      [[ -n "${rel}" ]] || die "environment ${env_key} declares no runtime directory"
      cell_dir="${bundle_dir}/${rel}"
      [[ -d "${cell_dir}" ]] || die "Missing ${rel} for environment ${env_key} (run build.sh first)"
      if [[ ${#modules[@]} -eq 0 ]]; then
        shopt -s nullglob
        matches=( "${cell_dir}"/*-sm"${sm}"-cu"${cuda}"-"${os_name}"-"${arch}"-py"${py}".so )
        shopt -u nullglob
        [[ ${#matches[@]} -ge 1 ]] || die "${rel} has no .so artifacts"
      else
        for mod in "${modules[@]}"; do
          pattern="${cell_dir}/${mod}*-sm${sm}-cu${cuda}-${os_name}-${arch}-py${py}.so"
          shopt -s nullglob
          matches=( ${pattern} )
          shopt -u nullglob
          [[ ${#matches[@]} -ge 1 ]] || die "Missing ${rel}/${mod}*.so"
        done
      fi
      log "${rel} OK"
    done
  done
}

pack_verify_lib_matrix_and_abi() {
  local bundle_dir="$1" sm="$2" cuda_tags="$3" os_name="$4" arch="$5" py_minors="$6"
  local native_lib="${bundle_dir}/lib"
  local -a modules=()
  if [[ -n "${RELEASE_NATIVE_MODULES:-}" ]]; then
    read -r -a modules <<< "${RELEASE_NATIVE_MODULES}"
  fi
  [[ -d "${native_lib}" ]] || {
    die "Missing ${native_lib}"
    return 1
  }

  verify_native_matrix_multi "${native_lib}" "${sm}" "${cuda_tags}" "${os_name}" "${arch}" \
    "${py_minors}" "${modules[@]}" \
    || die "lib/ matrix incomplete (expected sm${sm} × cu${cuda_tags} × py${py_minors})"

  if [[ -n "${RELEASE_MATRIX_SM120_CUDA_TAGS:-${SM120_CUDA_TAGS:-}}" ]]; then
    local sm120_cuda="${RELEASE_MATRIX_SM120_CUDA_TAGS:-${SM120_CUDA_TAGS}}"
    for cuda in ${sm120_cuda}; do
      if [[ ${#modules[@]} -eq 0 ]]; then
        verify_native_matrix_cell_any "${native_lib}" "120" "${cuda}" "${os_name}" "${arch}" \
          "${py_minors}" \
          || die "lib/ missing sm120-cu${cuda} cells (Blackwell)"
      else
        verify_native_matrix_lib "${native_lib}" "120" "${cuda}" "${os_name}" "${arch}" \
          "${py_minors}" "${modules[@]}" \
          || die "lib/ missing sm120-cu${cuda} cells (Blackwell)"
      fi
    done
  fi

  # Host pack may lack matrix interpreters; compile-time verify (build_release_matrix.sh) is strict.
  verify_native_lib_python_abi \
    "${bundle_dir}" "${sm}" "${cuda_tags}" "${os_name}" "${arch}" "${py_minors}" 0
}
