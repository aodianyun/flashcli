# Matrix + ABI verification before packing lib/*.so
# Requires: log, die, verify_native_matrix_multi, verify_native_lib_python_abi

pack_verify_lib_matrix_and_abi() {
  local bundle_dir="$1" sm="$2" cuda_tags="$3" os_name="$4" arch="$5" py_minors="$6"
  local native_lib="${bundle_dir}/lib"
  local -a modules=(flash_rt_kernels flash_rt_fa2)
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
      verify_native_matrix_lib "${native_lib}" "120" "${cuda}" "${os_name}" "${arch}" \
        "${py_minors}" "${modules[@]}" \
        || die "lib/ missing sm120-cu${cuda} cells (Blackwell)"
    done
  fi

  # Host pack may lack matrix interpreters; compile-time verify (build_release_matrix.sh) is strict.
  verify_native_lib_python_abi \
    "${bundle_dir}" "${sm}" "${cuda_tags}" "${os_name}" "${arch}" "${py_minors}" 0
}
