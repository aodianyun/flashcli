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
