# Manifest overlay helpers — flashcli-bundle.json is author-owned and read-only.
#
# Build/finalize write .build/manifest-overlay.json only.
# pack_bundle.sh merges overlay + lib/*.so into dist/flashcli-bundle.json.
#
# shellcheck shell=bash

manifest_overlay_path() {
  printf '%s/.build/manifest-overlay.json' "$1"
}

run_manifest_overlay() {
  # run_manifest_overlay BUNDLE_DIR LIB_DIR GEN_MANIFEST REPO_ROOT PYTHON_BIN \
  #   -- [extra args for generate_runtime_manifest.py]
  local bundle_dir="$1"
  local lib_dir="$2"
  local gen_manifest="$3"
  local repo_root="$4"
  local py_bin="$5"
  shift 5

  local overlay
  overlay="$(manifest_overlay_path "${bundle_dir}")"
  mkdir -p "${bundle_dir}/.build"
  printf '[manifest-overlay] Writing %s (flashcli-bundle.json unchanged)\n' "${overlay}" >&2
  "${py_bin}" "${gen_manifest}" \
    --repo-root "${repo_root}" \
    --bundle-json "${bundle_dir}/flashcli-bundle.json" \
    --output-json "${overlay}" \
    --lib-dir "${lib_dir}" \
    "$@" >/dev/null
}
