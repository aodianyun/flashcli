# Verify lib/ contains expected native matrix cells.
# Source from pack.sh / release matrix scripts:
#   source "${FLASHCLI_ROOT}/scripts/lib/verify_native_matrix.sh"
#
#   verify_native_matrix_lib "${BUNDLE_DIR}/lib" 120 130 linux x86_64 "310 311 312" \
#     flash_rt_kernels flash_rt_fa2

verify_native_matrix_lib() {
  local lib_dir="$1" sm="$2" cuda_tag="$3" os_name="$4" arch="$5" py_minors_csv="$6"
  shift 6
  local -a modules=("$@")
  local -a py_minors=()
  local py mod pattern
  local -a matches=()

  [[ -d "${lib_dir}" ]] || {
    printf '[matrix-verify] ERROR: missing lib dir: %s\n' "${lib_dir}" >&2
    return 1
  }

  # shellcheck disable=SC2206
  py_minors=(${py_minors_csv})

  for py in "${py_minors[@]}"; do
    for mod in "${modules[@]}"; do
      pattern="${mod}*-sm${sm}-cu${cuda_tag}-${os_name}-${arch}-py${py}.so"
      shopt -s nullglob
      matches=( "${lib_dir}"/${pattern} )
      shopt -u nullglob
      if [[ ${#matches[@]} -lt 1 ]]; then
        printf '[matrix-verify] ERROR: missing %s (expected %s)\n' "${mod}" "${pattern}" >&2
        return 1
      fi
      if [[ ${#matches[@]} -gt 1 ]]; then
        printf '[matrix-verify] WARN: multiple matches for %s: %s\n' "${pattern}" "${matches[*]}" >&2
      fi
    done
  done

  local expected=$(( ${#py_minors[@]} * ${#modules[@]} ))
  printf '[matrix-verify] OK sm%s-cu%s-%s-%s × py%s × %d modules (%d artifacts)\n' \
    "${sm}" "${cuda_tag}" "${os_name}" "${arch}" \
    "$(IFS=/; echo "${py_minors[*]}")" "${#modules[@]}" "${expected}" >&2
  return 0
}
