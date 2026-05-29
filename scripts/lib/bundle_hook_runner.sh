#!/usr/bin/env bash
# Run standard bundle hooks against bundles/<name>/_bundle_build.sh
#
#   bash scripts/lib/bundle_hook_runner.sh cell  /path/to/bundle --repo-root ...
#   bash scripts/lib/bundle_hook_runner.sh finalize /path/to/bundle --repo-root ...
#
set -euo pipefail

HOOK="${1:-}"
BUNDLE_DIR="${2:-}"
shift 2 || true

die() { printf '[bundle-hook] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "${HOOK}" == "cell" || "${HOOK}" == "finalize" ]] || die "hook must be cell or finalize"
[[ -n "${BUNDLE_DIR}" && -d "${BUNDLE_DIR}" ]] || die "bundle dir required"
BUNDLE_DIR="$(cd "${BUNDLE_DIR}" && pwd)"

BUILD_SH="${BUNDLE_DIR}/_bundle_build.sh"
ENV_FILE="${BUNDLE_DIR}/release-matrix.env"
[[ -f "${BUILD_SH}" ]] || die "Missing ${BUILD_SH}"
[[ -f "${ENV_FILE}" ]] || die "Missing ${ENV_FILE}"

# shellcheck source=/dev/null
source "${ENV_FILE}"

append_extra_args() {
  local -n _out="$1"
  local extra
  if [[ "${HOOK}" == "finalize" ]]; then
    extra="${RELEASE_FINALIZE_EXTRA:-${RELEASE_CELL_EXTRA:-${RELEASE_BUILD_MATRIX_EXTRA:-}}}"
  else
    extra="${RELEASE_CELL_EXTRA:-${RELEASE_BUILD_MATRIX_EXTRA:-}}"
  fi
  if [[ -n "${extra}" ]]; then
    local -a parsed=()
    read -r -a parsed <<< "${extra}"
    _out+=("${parsed[@]}")
  fi
}

run_hook() {
  local -a hook_args=("$@")
  append_extra_args hook_args
  exec bash "${BUILD_SH}" "${hook_args[@]}"
}

case "${HOOK}" in
  cell) run_hook --merge-native --skip-manifest "$@" ;;
  finalize) run_hook --finalize-matrix-manifest --pack-only "$@" ;;
esac
