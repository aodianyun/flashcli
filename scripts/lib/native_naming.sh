# Shared native .so naming: {module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
# Source from build scripts: source "$(dirname "$0")/lib/native_naming.sh"

sanitize_flashrt_abi() {
  local tag="${1:-dev}" commit="${2:-}"
  local out
  out="$(printf '%s' "${tag}" | sed 's/[^a-zA-Z0-9._-]/-/g; s/^-*//; s/-*$//')"
  if [[ -z "${out}" || ${#out} -gt 40 ]]; then
    out="${commit:0:12}"
    [[ -n "${out}" ]] || out="dev"
  fi
  printf '%s\n' "${out}"
}

native_artifact_tag() {
  local flashrt_abi="$1" sm="$2" cuda_tag="$3" os_name="$4" arch="$5" py="$6"
  sm="${sm#sm}" sm="${sm#SM}"
  cuda_tag="${cuda_tag#cu}" cuda_tag="${cuda_tag#CU}"
  py="${py#py}" py="${py#PY}"
  printf '%s-sm%s-cu%s-%s-%s-py%s\n' \
    "${flashrt_abi}" "${sm}" "${cuda_tag}" "${os_name}" "${arch}" "${py}"
}

native_so_filename() {
  local module_base="$1" tag="$2"
  printf '%s-%s.so\n' "${module_base}" "${tag}"
}

# Pick a CMake/pybind output .so for the requested Python ABI (e.g. cpython-311).
pick_built_native_so() {
  local src_dir="$1" module_base="$2" py_minor="$3"
  local major="${py_minor:0:1}" minor="${py_minor:1:2}"
  local needle="cpython-${major}${minor}"
  local -a matches=()
  local m

  shopt -s nullglob
  matches=( "${src_dir}/${module_base}"*.so )
  shopt -u nullglob
  [[ ${#matches[@]} -gt 0 ]] || return 1

  for m in "${matches[@]}"; do
    if [[ "$(basename "${m}")" == *"${needle}"* ]]; then
      printf '%s\n' "${m}"
      return 0
    fi
  done
  if [[ ${#matches[@]} -eq 1 ]]; then
    printf '[native-stage] ERROR: only one %s*.so in %s but ABI mismatch (need %s, got %s)\n' \
      "${module_base}" "${src_dir}" "${needle}" "$(basename "${matches[0]}")" >&2
    return 1
  fi
  printf '[native-stage] ERROR: %d %s*.so in %s, none match Python %s (%s)\n' \
    "${#matches[@]}" "${module_base}" "${src_dir}" "${py_minor}" "${needle}" >&2
  for m in "${matches[@]}"; do
    printf '  %s\n' "${m}" >&2
  done
  return 1
}

stage_native_module_to_lib() {
  local src_dir="$1" lib_dir="$2" module_base="$3" dest_name="$4" py_minor="$5"
  local picked
  picked="$(pick_built_native_so "${src_dir}" "${module_base}" "${py_minor}")" || return 1
  cp -f "${picked}" "${lib_dir}/${dest_name}"
}

clean_flashrt_shared_native_outputs() {
  local repo_root="$1"
  rm -f \
    "${repo_root}/flash_rt/flash_rt_kernels"*.so \
    "${repo_root}/flash_rt/flash_rt_fa2"*.so \
    "${repo_root}/flash_rt/flash_rt_fp4"*.so
}

snapshot_flashrt_native_to_build_dir() {
  local repo_root="$1" build_dir="$2"
  local out="${build_dir}/native-out"
  mkdir -p "${out}"
  rm -f "${out}"/*.so
  shopt -s nullglob
  local f
  for f in \
    "${repo_root}/flash_rt/flash_rt_kernels"*.so \
    "${repo_root}/flash_rt/flash_rt_fa2"*.so \
    "${repo_root}/flash_rt/flash_rt_fp4"*.so; do
    [[ -f "${f}" ]] || continue
    cp -f "${f}" "${out}/"
  done
  shopt -u nullglob
}
