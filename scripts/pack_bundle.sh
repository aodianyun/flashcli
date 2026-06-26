#!/usr/bin/env bash
# Pack bundle release: bundle tree + per-env runtime/ directories for FlashHub.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/load_release_matrix.sh
source "${SCRIPT_DIR}/lib/load_release_matrix.sh"
# shellcheck source=lib/make_zip.sh
source "${SCRIPT_DIR}/lib/make_zip.sh"
# shellcheck source=lib/verify_native_matrix.sh
source "${SCRIPT_DIR}/lib/verify_native_matrix.sh"
# shellcheck source=lib/probe_native_abi.sh
source "${SCRIPT_DIR}/lib/probe_native_abi.sh"
# shellcheck source=lib/native_naming.sh
source "${SCRIPT_DIR}/lib/native_naming.sh"
# shellcheck source=lib/release_naming.sh
source "${SCRIPT_DIR}/lib/release_naming.sh"
# shellcheck source=lib/verify_native_abi.sh
source "${SCRIPT_DIR}/lib/verify_native_abi.sh"
# shellcheck source=lib/pack_verify.sh
source "${SCRIPT_DIR}/lib/pack_verify.sh"
# shellcheck source=lib/matrix_python.sh
source "${SCRIPT_DIR}/lib/matrix_python.sh"

BUNDLE_ARG=""
BUNDLE_DIR=""
REPO_ROOT="${FLASHRT_REPO:-}"
OUTPUT_DIR=""
SKIP_MATRIX_VERIFY=0
OS_NAME="linux"
ARCH="x86_64"

log() { printf '[pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Pack split bundle artifacts for FlashHub (format_version 3).

Outputs under dist/:
  flashcli-bundle.json + bundle source tree (run.py, flash_rt/, …)
  runtime/<env-key>/ — per-env native .so files

Usage:
  bash scripts/pack_bundle.sh [OPTIONS]
EOF
}

is_flashrt_repo() {
  [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]
}

resolve_repo_root() {
  if [[ -n "${REPO_ROOT}" ]]; then
    REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
    is_flashrt_repo "${REPO_ROOT}" || die "Invalid FlashRT repo: ${REPO_ROOT}"
    return
  fi
  local candidate
  for candidate in \
    "$(cd "${FLASHCLI_ROOT}/.." && pwd)" \
    "$(cd "${FLASHCLI_ROOT}/../.." && pwd)"; do
    if is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      log "FlashRT repo: ${REPO_ROOT} (auto-detected)"
      return
    fi
  done
  die "Set FLASHRT_REPO or pass --repo-root"
}

make_tar_gz() {
  local src_dir="$1"
  local out="$2"
  rm -f "${out}"
  tar -czf "${out}" -C "${src_dir}" .
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --bundle) BUNDLE_ARG="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --skip-matrix-verify) SKIP_MATRIX_VERIFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ -n "${BUNDLE_DIR}" ]]; then
  BUNDLE_DIR="$(cd "${BUNDLE_DIR}" && pwd)"
else
  BUNDLE_DIR="$(resolve_bundle_dir "${FLASHCLI_ROOT}" "${BUNDLE_ARG}")" \
    || die "Cannot resolve bundle directory"
fi

load_release_matrix_config "${BUNDLE_DIR}" || die "Invalid release-matrix.env"
resolve_repo_root

PYTHON_ABI="${RELEASE_PYTHON_ABI:-312}"
  PY_MINORS="${RELEASE_MATRIX_PY_MINORS:-${PYTHON_ABI}}"
  PACK_FILES="${RELEASE_PACK_FILES:-}"
  NATIVE_MODULES="${RELEASE_NATIVE_MODULES:-flash_rt_kernels flash_rt_fa2}"
  [[ -n "${PACK_FILES}" ]] || die "RELEASE_PACK_FILES not set in release-matrix.env"

native_lib="${BUNDLE_DIR}/lib"
[[ -d "${native_lib}" ]] || die "Missing lib/ (run release_bundle.sh first)"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/"

if [[ "${SKIP_MATRIX_VERIFY}" -eq 0 ]]; then
  pack_verify_lib_matrix_and_abi \
    "${BUNDLE_DIR}" "${MATRIX_SM}" "${CUDA_TAGS}" "${OS_NAME}" "${ARCH}" "${PY_MINORS}"
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${BUNDLE_DIR}/dist"
else
  OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
fi
mkdir -p "${OUTPUT_DIR}/runtime"

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

for entry in ${PACK_FILES}; do
  [[ "${entry}" != "lib" ]] || continue
  local_path="${BUNDLE_DIR}/${entry}"
  [[ -e "${local_path}" ]] || die "Missing pack file: ${entry}"
  if [[ -d "${local_path}" ]]; then
    mkdir -p "${OUTPUT_DIR}/${entry}"
    cp -a "${local_path}/." "${OUTPUT_DIR}/${entry}/"
  else
    cp -a "${local_path}" "${OUTPUT_DIR}/"
  fi
done
log "Copied bundle tree to ${OUTPUT_DIR}"

# Native cells: group lib/*.so into runtime/<env-key>/ via Python (see below).
shopt -s nullglob
shopt -u nullglob

python3 - "${BUNDLE_DIR}" "${OUTPUT_DIR}" "${PYTHON_ABI}" "${FLASHCLI_ROOT}" <<'PY'
import json
import shutil
import sys
from pathlib import Path

bundle_dir = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
py_abi = sys.argv[3]
flashcli_root = Path(sys.argv[4])
scripts_lib = flashcli_root / "scripts" / "lib"
sys.path.insert(0, str(scripts_lib))
from flashcli_bundle_path import ensure_flashcli_bundle_on_path

ensure_flashcli_bundle_on_path(flashcli_root)
from flashcli_bundle.native_naming import parse_native_tag_from_filename

lib = bundle_dir / "lib"
manifest_path = bundle_dir / "flashcli-bundle.json"
manifest = json.loads(manifest_path.read_text())
cells: dict[str, list[Path]] = {}
for so in sorted(lib.glob("*.so")):
    parsed = parse_native_tag_from_filename(so.name)
    if parsed is None or parsed.python_minor != py_abi:
        continue
    key = parsed.catalog_key()
    cells.setdefault(key, []).append(so)

runtime_map = {}
for key, paths in sorted(cells.items()):
    dest = out_dir / "runtime" / key
    if dest.is_dir():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for p in paths:
        shutil.copy2(p, dest / p.name)
    runtime_map[key] = f"runtime/{key}"
    print(f"[pack] Created {dest} ({len(paths)} .so)", file=sys.stderr)

manifest["format_version"] = 3
manifest["python_abi"] = py_abi
manifest["runtime"] = runtime_map
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
shutil.copy2(manifest_path, out_dir / "flashcli-bundle.json")
print(f"[pack] Updated {manifest_path} and copied to {out_dir / 'flashcli-bundle.json'}", file=sys.stderr)
PY

log "FlashHub upload dir: ${OUTPUT_DIR}"
