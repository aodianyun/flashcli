# Release archive naming (FlashRT ABI + build timestamp).
# Source after native_naming.sh:
#   source scripts/lib/release_naming.sh

sanitize_release_segment() {
  local s="$1"
  s="$(printf '%s' "${s}" | sed 's/[^a-zA-Z0-9._-]/-/g; s/^-*//; s/-*$//')"
  [[ -n "${s}" ]] || s="dev"
  if [[ ${#s} -gt 48 ]]; then
    s="${s:0:48}"
  fi
  printf '%s\n' "${s}"
}

flashrt_release_abi() {
  local repo_root="$1"
  local flashrt_tag commit abi
  flashrt_tag="$(git -C "${repo_root}" describe --tags --always 2>/dev/null || echo dev)"
  commit="$(git -C "${repo_root}" rev-parse HEAD 2>/dev/null || echo unknown)"
  if declare -f sanitize_flashrt_abi >/dev/null 2>&1; then
    abi="$(sanitize_flashrt_abi "${flashrt_tag}" "${commit}")"
  else
    abi="$(sanitize_release_segment "${flashrt_tag}")"
  fi
  printf '%s\n' "${abi}"
}

release_build_stamp() {
  date +%Y%m%d-%H%M%S
}

# flashcli-bundle-pi05-{flashrt_abi}-sm89-multi-linux-x86_64-{YYYYMMDD-HHMMSS}
release_archive_basename() {
  local zip_prefix="$1" repo_root="$2" sm="$3" os_name="$4" arch="$5"
  local abi stamp
  abi="$(flashrt_release_abi "${repo_root}")"
  stamp="$(release_build_stamp)"
  printf '%s-%s-sm%s-multi-%s-%s-%s\n' \
    "${zip_prefix}" "${abi}" "${sm}" "${os_name}" "${arch}" "${stamp}"
}
