#!/usr/bin/env bash
# Native-only pack for pi05_libero_nexus.
#
# Packs the bundle root (flashcli-bundle.json) + runtime/<env>/substrate/ C
# libraries. No Python tree is included (no flash_rt/, no *_substrate_loader.py,
# no nexus_python) — inference runs through the native model-runtime ABI.
#
#   bash pack.sh [--output-dir DIR]
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR=""
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --output-dir) OUTPUT_DIR="${ARGS[$((i + 1))]}" ;;
  esac
done
[[ -n "${OUTPUT_DIR}" ]] || OUTPUT_DIR="${BUNDLE_DIR}/dist"

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || {
  echo "error: missing flashcli-bundle.json" >&2
  exit 1
}
cp -a "${BUNDLE_DIR}/flashcli-bundle.json" "${OUTPUT_DIR}/flashcli-bundle.json"

if [[ -d "${BUNDLE_DIR}/runtime" ]]; then
  mkdir -p "${OUTPUT_DIR}/runtime"
  cp -a "${BUNDLE_DIR}/runtime/." "${OUTPUT_DIR}/runtime/"
fi

python3 - "${BUNDLE_DIR}" "${OUTPUT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
out = Path(sys.argv[2])
manifest = json.loads((bundle / "flashcli-bundle.json").read_text())
overlay = bundle / ".build" / "manifest-overlay.json"
if overlay.is_file():
    o = json.loads(overlay.read_text())
    for key in ("format_version", "build"):
        if key in o:
            manifest[key] = o[key]
    if o.get("python_abi"):
        manifest["python_abi"] = o["python_abi"]
    if o.get("runtime"):
        manifest["runtime"] = o["runtime"]
(out / "flashcli-bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"[pack] wrote {out / 'flashcli-bundle.json'}")
PY

echo "[pack] native bundle tree:"
find "${OUTPUT_DIR}" -type f | sort
