# Load bundle release-matrix.env and export normalized variables.
#
#   source scripts/lib/load_release_matrix.sh
#   load_release_matrix_config /path/to/bundles/pi05_libero
#
# Sets: BUNDLE_DIR, RELEASE_* and derived MATRIX_SM, CUDA_TAGS, PY_MINORS, etc.

load_release_matrix_config() {
  local bundle_dir="$1"
  local env_file="${bundle_dir}/release-matrix.env"
  [[ -f "${env_file}" ]] || {
    printf '[release-matrix] ERROR: missing %s\n' "${env_file}" >&2
    return 1
  }
  # shellcheck source=/dev/null
  source "${env_file}"

  BUNDLE_DIR="$(cd "${bundle_dir}" && pwd)"
  RELEASE_BUNDLE_NAME="${RELEASE_BUNDLE_NAME:-}"
  MATRIX_SM="${RELEASE_MATRIX_SM:-}"
  CUDA_TAGS="${RELEASE_MATRIX_CUDA_TAGS:-}"
  PY_MINORS="${RELEASE_MATRIX_PY_MINORS:-}"
  ZIP_PREFIX="${RELEASE_ZIP_PREFIX:-}"
  FINALIZE_CUDA_TAG="${RELEASE_FINALIZE_CUDA_TAG:-130}"
  IMAGE_CU124="${RELEASE_DOCKER_IMAGE_CU124:-nvcr.io/nvidia/pytorch:24.05-py3}"
  IMAGE_CU130="${RELEASE_DOCKER_IMAGE_CU130:-nvcr.io/nvidia/pytorch:25.10-py3}"
  BUILD_MATRIX_EXTRA="${RELEASE_BUILD_MATRIX_EXTRA:-}"
  CELL_EXTRA="${RELEASE_CELL_EXTRA:-${BUILD_MATRIX_EXTRA}}"
  FINALIZE_EXTRA="${RELEASE_FINALIZE_EXTRA:-${CELL_EXTRA}}"
  PACK_FILES="${RELEASE_PACK_FILES:-}"
  SM120_CUDA_TAGS="${RELEASE_MATRIX_SM120_CUDA_TAGS:-}"
  NATIVE_MODULES="${RELEASE_NATIVE_MODULES:-flash_rt_kernels flash_rt_fa2}"

  local missing=()
  [[ -n "${RELEASE_BUNDLE_NAME}" ]] || missing+=("RELEASE_BUNDLE_NAME")
  [[ -n "${MATRIX_SM}" ]] || missing+=("RELEASE_MATRIX_SM")
  [[ -n "${CUDA_TAGS}" ]] || missing+=("RELEASE_MATRIX_CUDA_TAGS")
  [[ -n "${PY_MINORS}" ]] || missing+=("RELEASE_MATRIX_PY_MINORS")
  [[ -n "${ZIP_PREFIX}" ]] || missing+=("RELEASE_ZIP_PREFIX")
  [[ -n "${PACK_FILES}" ]] || missing+=("RELEASE_PACK_FILES")
  if [[ ${#missing[@]} -gt 0 ]]; then
    printf '[release-matrix] ERROR: %s incomplete: %s\n' "${env_file}" "${missing[*]}" >&2
    return 1
  fi

  [[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || {
    printf '[release-matrix] ERROR: missing flashcli-bundle.json in %s\n' "${BUNDLE_DIR}" >&2
    return 1
  }
  # shellcheck source=bundle_hooks.sh
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bundle_hooks.sh"
  require_bundle_hooks "${BUNDLE_DIR}" || return 1
  return 0
}

# Resolve bundle directory from --bundle NAME or current bundle tree.
resolve_bundle_dir() {
  local flashcli_root="$1" bundle_arg="${2:-}"
  if [[ -n "${bundle_arg}" ]]; then
    local candidate="${flashcli_root}/bundles/${bundle_arg}"
    [[ -d "${candidate}" ]] || {
      printf '[release-matrix] ERROR: bundle not found: %s\n' "${candidate}" >&2
      return 1
    }
    printf '%s\n' "${candidate}"
    return 0
  fi
  # Auto: cwd inside bundles/<name>/
  local cwd
  cwd="$(pwd)"
  if [[ -f "${cwd}/release-matrix.env" ]]; then
    printf '%s\n' "${cwd}"
    return 0
  fi
  printf '[release-matrix] ERROR: pass --bundle NAME or run from bundles/<name>/\n' >&2
  return 1
}
