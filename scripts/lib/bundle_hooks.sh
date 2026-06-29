# Bundle hook contract for scripts/build_release_matrix.sh and scripts/release_bundle.sh
#
# Each publishable bundle MUST provide under bundles/<name>/:
#
#   release-matrix.env     Matrix dimensions, docker images, pack file list
#   _bundle_build.sh       Bundle-specific cmake/staging implementation
#
# Optional:
#   build.sh               Local dev (single env); not used by release pipeline
#   release.sh             exec scripts/release_bundle.sh --bundle <name>
#   pack.sh                Thin wrapper → scripts/pack_bundle.sh
#
# release-matrix.env required fields:
#   RELEASE_BUNDLE_NAME, RELEASE_MATRIX_SM, RELEASE_MATRIX_CUDA_TAGS,
#   RELEASE_MATRIX_PY_MINORS, RELEASE_ZIP_PREFIX, RELEASE_PACK_FILES
#
# Optional env fields:
#   RELEASE_CELL_EXTRA       Extra args for matrix cell builds (e.g. --variant all)
#   RELEASE_FINALIZE_EXTRA   Extra args for manifest finalize (defaults to CELL_EXTRA)
#   RELEASE_BUILD_MATRIX_EXTRA  Legacy alias for RELEASE_CELL_EXTRA
#
# Matrix cell / finalize are run via scripts/lib/bundle_hook_runner.sh → _bundle_build.sh
#
# matrix cell contract
# --------------------
# Called with:
#   --repo-root DIR --python-bin PATH --python-minor NNN --sm SM --cuda-tag TAG
#   --build-dir DIR --git-ref REF -j N
#   plus RELEASE_CELL_EXTRA from release-matrix.env
#
# MUST:
#   - Add/update only this cell's tagged .so under lib/
#   - Leave other lib/*.so cells untouched (--merge-native semantics)
#   - NOT modify flashcli-bundle.json (author manifest; write overlay only on finalize)
#   - NOT write dist/ or delete lib/ siblings
#
# finalize contract
# -----------------
# Called with: --repo-root DIR --sm SM --cuda-tag TAG --git-ref REF
# MUST: scan lib/*.so and write .build/manifest-overlay.json (not flashcli-bundle.json)
# MUST NOT: run cmake or remove lib/ artifacts
#
# pack contract (scripts/pack_bundle.sh)
# --------------------------------------
# Called with: --bundle-dir DIR --repo-root DIR
# MUST: verify matrix + ABI, write dist/<zip> from RELEASE_PACK_FILES only
# MUST NOT: modify bundles/<name>/flashcli-bundle.json (author manifest); merge
#           overlay + runtime map into dist/flashcli-bundle.json only
# Zip name: {ZIP_PREFIX}-{flashrt_abi}-sm{SM}-multi-{os}-{arch}-{YYYYMMDD-HHMMSS}

bundle_hook_runner() {
  printf '%s/lib/bundle_hook_runner.sh\n' "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
}

bundle_pack_script() {
  printf '%s/../pack_bundle.sh\n' "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
}

require_bundle_hooks() {
  local bundle_dir="$1"
  local env_file="${bundle_dir}/release-matrix.env"
  local missing=()

  [[ -f "${env_file}" ]] || missing+=("release-matrix.env")
  [[ -f "${bundle_dir}/_bundle_build.sh" ]] || missing+=("_bundle_build.sh")

  if [[ ${#missing[@]} -gt 0 ]]; then
    printf '[bundle-hooks] ERROR: %s missing: %s\n' "${bundle_dir}" "${missing[*]}" >&2
    return 1
  fi

  # shellcheck source=/dev/null
  source "${env_file}"
  if [[ -z "${RELEASE_PACK_FILES:-}" ]]; then
    printf '[bundle-hooks] ERROR: %s missing RELEASE_PACK_FILES in release-matrix.env\n' "${bundle_dir}" >&2
    return 1
  fi
  return 0
}
