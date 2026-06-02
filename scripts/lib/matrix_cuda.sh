# CUDA toolkit selection for release matrix builds.
# Source after defining log/die:
#   source scripts/lib/matrix_cuda.sh

cuda_home_for_tag() {
  local tag="$1"
  local var="CUDA_HOME_CU${tag}"
  local home="${!var:-}"
  if [[ -n "${home}" ]]; then
    printf '%s\n' "${home}"
    return
  fi
  case "${tag}" in
    124)
      for home in /usr/local/cuda-12.4 /usr/local/cuda-12.6 /usr/local/cuda-12; do
        [[ -x "${home}/bin/nvcc" ]] && { printf '%s\n' "${home}"; return; }
      done
      ;;
    130)
      for home in /usr/local/cuda-13.0 /usr/local/cuda-13 /usr/local/cuda; do
        [[ -x "${home}/bin/nvcc" ]] && { printf '%s\n' "${home}"; return; }
      done
      ;;
  esac
  if [[ -n "${CUDA_HOME:-}" && -x "${CUDA_HOME}/bin/nvcc" ]]; then
    printf '%s\n' "${CUDA_HOME}"
    return
  fi
  printf '\n'
}

nvcc_release_for_tag() {
  case "$1" in
    124) echo "12.4" ;;
    130) echo "13.0" ;;
    *) echo "?" ;;
  esac
}

nvcc_tag_from_version() {
  local ver="$1"
  case "${ver}" in
    12.4|12.5|12.6) echo "124" ;;
    12.8|12.9) echo "128" ;;
    13.*) echo "130" ;;
    *)
      local compact="${ver//./}"
      echo "${compact:0:3}"
      ;;
  esac
}

activate_cuda_toolkit() {
  local tag="$1" skip_verify="${2:-0}"
  local home
  home="$(cuda_home_for_tag "${tag}")"
  if [[ -z "${home}" ]]; then
    die "No CUDA toolkit for cu${tag}. Set CUDA_HOME_CU${tag} (e.g. export CUDA_HOME_CU130=/usr/local/cuda-13.0)"
    return 1
  fi
  export CUDA_HOME="${home}"
  export PATH="${CUDA_HOME}/bin:${PATH}"
  command -v nvcc >/dev/null 2>&1 || die "nvcc not found under ${CUDA_HOME}"
  local ver detected_tag
  ver="$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p' | head -1)"
  detected_tag="$(nvcc_tag_from_version "${ver}")"
  log "cu${tag}: CUDA_HOME=${CUDA_HOME} nvcc=${ver} (detected tag ${detected_tag})"
  if [[ "${skip_verify}" -eq 0 && "${detected_tag}" != "${tag}" ]]; then
    die "nvcc ${ver} does not match requested cu${tag} (expected ~$(nvcc_release_for_tag "${tag}")). Fix CUDA_HOME_CU${tag} or use --cuda-tag ${detected_tag}"
  fi
}
