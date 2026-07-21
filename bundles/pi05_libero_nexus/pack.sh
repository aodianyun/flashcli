#!/usr/bin/env bash
# Thin wrapper → scripts/pack_bundle.sh, then re-stage the substrate/ subdir.
#
# The upstream pack_bundle.sh copies only top-level *.so from each runtime
# cell (existing bundles have no subdirs). This wrapper re-copies the
# substrate/ subdir (C libs + nexus_python + VERSION) after pack, so the
# dist/ is fully self-contained.
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"

bash "${FLASHCLI_ROOT}/scripts/pack_bundle.sh" --bundle-dir "${BUNDLE_DIR}" "$@"

# pack_bundle.sh writes the OUTPUT_DIR from --output-dir or defaults to
# ${BUNDLE_DIR}/dist. Re-detect to find the dist dir.
OUTPUT_DIR=""
ARGS=("$@")
for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --output-dir) OUTPUT_DIR="${ARGS[$((i+1))]}"; break ;;
  esac
done
[[ -n "${OUTPUT_DIR}" ]] || OUTPUT_DIR="${BUNDLE_DIR}/dist"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"

# Re-stage substrate/ for every runtime cell that has one.
shopt -s nullglob
for src_cell in "${BUNDLE_DIR}/runtime/"*/; do
  cell_name="$(basename "${src_cell}")"
  sub_src="${src_cell}substrate"
  [[ -d "${sub_src}" ]] || continue
  sub_dst="${OUTPUT_DIR}/runtime/${cell_name}/substrate"
  mkdir -p "${sub_dst}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "${sub_src}/" "${sub_dst}/"
  else
    rm -rf "${sub_dst}"
    cp -a "${sub_src}" "${sub_dst}"
  fi
  echo "[pack] runtime/${cell_name}/substrate ($(find "${sub_dst}" -type f | wc -l) files)"
done
shopt -u nullglob

echo "[pack] substrate re-staged; dist: ${OUTPUT_DIR}"
