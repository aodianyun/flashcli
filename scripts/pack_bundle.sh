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
VERIFY_MATRIX=0
ALL_ENVS=0
CURRENT_ENV_KEY="${FLASHCLI_RUNTIME_ENV_KEY:-}"
OS_NAME="linux"
ARCH="x86_64"

log() { printf '[pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Pack split bundle artifacts for FlashHub. Default: current environment only.
Use --all-envs/--verify-matrix for a full release matrix.

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
    --skip-matrix-verify) VERIFY_MATRIX=0; shift ;;
    --verify-matrix) VERIFY_MATRIX=1; shift ;;
    --all-envs) ALL_ENVS=1; shift ;;
    --env-key) CURRENT_ENV_KEY="$2"; shift 2 ;;
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
runtime_root="${BUNDLE_DIR}/runtime"
PACK_NATIVE_LAYOUT="lib"
if [[ -d "${runtime_root}" ]]; then
  shopt -s nullglob
  for _cell in "${runtime_root}"/*/; do
    PACK_NATIVE_LAYOUT="runtime"
    break
  done
  shopt -u nullglob
fi
if [[ "${PACK_NATIVE_LAYOUT}" == "lib" && ! -d "${native_lib}" ]]; then
  PACK_NATIVE_LAYOUT="none"
fi

if [[ "${VERIFY_MATRIX}" -eq 1 && "${PACK_NATIVE_LAYOUT}" != "none" ]]; then
  if [[ "${PACK_NATIVE_LAYOUT}" == "runtime" ]]; then
    pack_verify_runtime_matrix \
      "${BUNDLE_DIR}" "${MATRIX_SM}" "${CUDA_TAGS}" "${OS_NAME}" "${ARCH}" "${PY_MINORS}"
  else
    pack_verify_lib_matrix_and_abi \
      "${BUNDLE_DIR}" "${MATRIX_SM}" "${CUDA_TAGS}" "${OS_NAME}" "${ARCH}" "${PY_MINORS}"
  fi
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${BUNDLE_DIR}/dist"
else
  OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
fi
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}/runtime"

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

for entry in ${PACK_FILES}; do
  [[ "${entry}" != "lib" && "${entry}" != "runtime" ]] || continue
  local_path="${BUNDLE_DIR}/${entry}"
  [[ -e "${local_path}" ]] || die "Missing pack file: ${entry}"
  if [[ -d "${local_path}" ]]; then
    mkdir -p "${OUTPUT_DIR}/${entry}"
    cp -a "${local_path}/." "${OUTPUT_DIR}/${entry}/"
  else
    cp -a "${local_path}" "${OUTPUT_DIR}/"
  fi
done
find "${OUTPUT_DIR}" -type f -name '*.so' -delete 2>/dev/null || true
find "${OUTPUT_DIR}" -type f -name '*.pyc' -delete 2>/dev/null || true
find "${OUTPUT_DIR}" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
log "Copied bundle tree to ${OUTPUT_DIR}"

# Native cells: current runtime/<env-key>/ → dist; --all-envs copies the full set.
python3 - "${BUNDLE_DIR}" "${OUTPUT_DIR}" "${PYTHON_ABI}" "${FLASHCLI_ROOT}" "${PACK_NATIVE_LAYOUT}" "${ALL_ENVS}" "${CURRENT_ENV_KEY}" "${REPO_ROOT}" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

bundle_dir = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
py_abi = sys.argv[3]
flashcli_root = Path(sys.argv[4])
pack_layout = sys.argv[5]
all_envs = sys.argv[6] == "1"
current_env_key = sys.argv[7].strip()
repo_root = Path(sys.argv[8])
scripts_lib = flashcli_root / "scripts" / "lib"
sys.path.insert(0, str(scripts_lib))
from flashcli_bundle_path import ensure_flashcli_bundle_on_path

ensure_flashcli_bundle_on_path(flashcli_root)
from flashcli_bundle.native_naming import parse_native_tag_from_filename

source_manifest_path = bundle_dir / "flashcli-bundle.json"
overlay_path = bundle_dir / ".build" / "manifest-overlay.json"
manifest = json.loads(source_manifest_path.read_text())
is_v4 = int(manifest.get("format_version", 3)) >= 4
overlay = json.loads(overlay_path.read_text()) if overlay_path.is_file() else {}
if not is_v4 and overlay:
    for key in ("format_version", "python_abi", "runtime", "build"):
        if key in overlay:
            manifest[key] = overlay[key]

def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""

if is_v4:
    overlay_build = overlay.get("build") if isinstance(overlay.get("build"), dict) else {}
    sources = []
    raw_sources = overlay_build.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            source = str(item.get("source") or "").strip()
            commit = str(item.get("commit") or "").strip()
            if name and source and commit:
                sources.append({"name": name, "source": source, "commit": commit})
    if not sources:
        source = str(overlay_build.get("source") or "").strip()
        if not source:
            source = _git("remote", "get-url", "origin") or _git("config", "--get", "remote.origin.url")
        commit = str(overlay_build.get("git_commit") or "").strip() or _git("rev-parse", "HEAD")
        sources.append({
            "name": "flashrt",
            "source": source or "unknown",
            "commit": commit or "unknown",
        })
    manifest["build"] = {"sources": sources}
elif "build" not in manifest:
    manifest["build"] = {
        "flashrt_tag": _git("describe", "--tags", "--always") or "unknown",
        "git_commit": _git("rev-parse", "HEAD") or "unknown",
        "git_ref": _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
    }

if is_v4:
    environments = manifest.get("environments")
    if not isinstance(environments, dict) or not environments:
        raise SystemExit("v4 manifest missing environments")

    def env_runtime(key: str) -> str:
        block = environments.get(key)
        if not isinstance(block, dict):
            return ""
        return str(block.get("runtime") or "").strip().strip("/")

    unique_rels = []
    for key in environments:
        rel = env_runtime(key)
        if rel and rel not in unique_rels:
            unique_rels.append(rel)

    if all_envs:
        selected_rels = list(unique_rels)
        selected_keys = list(environments)
    elif current_env_key:
        if current_env_key not in environments:
            raise SystemExit(f"environment {current_env_key!r} is not declared")
        target = env_runtime(current_env_key)
        selected_rels = [target] if target else []
        selected_keys = [k for k in environments if env_runtime(k) == target]
    elif len(unique_rels) == 1:
        selected_rels = unique_rels
        selected_keys = [k for k in environments if env_runtime(k) == selected_rels[0]]
    elif len(unique_rels) == 0:
        selected_rels = []
        selected_keys = list(environments)
    else:
        raise SystemExit("multiple runtime cells declared; pass --env-key KEY or --all-envs")

    for rel in selected_rels:
        src = (bundle_dir / rel).resolve()
        try:
            src.relative_to(bundle_dir.resolve())
        except ValueError:
            raise SystemExit(f"runtime path escapes bundle root: {rel!r}")
        if not src.is_dir():
            raise SystemExit(f"missing runtime directory: {src}")
        dest = out_dir / rel
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        for path in dest.rglob("*.pyc"):
            path.unlink()
        for path in sorted(dest.rglob("__pycache__"), reverse=True):
            shutil.rmtree(path, ignore_errors=True)
        print(f"[pack] {rel}", file=sys.stderr)

    manifest["environments"] = {k: environments[k] for k in selected_keys}
    for key, block in manifest["environments"].items():
        if not isinstance(block, dict):
            continue
        rel = env_runtime(key)
        if rel:
            block["runtime"] = rel
        else:
            block.pop("runtime", None)
    manifest.pop("runtime", None)
    if not selected_rels:
        shutil.rmtree(out_dir / "runtime", ignore_errors=True)
else:
    runtime_map: dict[str, str] = {}
    if pack_layout == "runtime":
        runtime_root = bundle_dir / "runtime"
        cells = [(d, sorted(d.glob("*.so"))) for d in sorted(runtime_root.iterdir()) if d.is_dir()]
        cells = [(d, sos) for d, sos in cells if sos]
    else:
        lib = bundle_dir / "lib"
        parsed_cells: dict[str, list[Path]] = {}
        for so in sorted(lib.glob("*.so")):
            parsed = parse_native_tag_from_filename(so.name)
            if parsed is None or parsed.python_minor != py_abi:
                continue
            parsed_cells.setdefault(parsed.catalog_key(), []).append(so)
        cells = [(Path(key), paths) for key, paths in sorted(parsed_cells.items())]

    if not all_envs:
        if current_env_key:
            cells = [(d, sos) for d, sos in cells if d.name == current_env_key]
            if not cells:
                raise SystemExit(f"environment {current_env_key!r} not staged under {bundle_dir}/runtime")
        elif len(cells) != 1:
            raise SystemExit("multiple runtime cells staged; pass --env-key KEY or --all-envs")
    if not cells:
        raise SystemExit("no staged runtime cells")

    for cell, sos in cells:
        key = cell.name
        dest = out_dir / "runtime" / key
        if dest.is_dir():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for p in sos:
            shutil.copy2(p, dest / p.name)
        runtime_map[key] = f"runtime/{key}"
        print(f"[pack] runtime/{key} ({len(sos)} .so)", file=sys.stderr)

    environments = manifest.get("environments")
    if isinstance(environments, dict):
        for key in runtime_map:
            environments.setdefault(key, {})["runtime"] = runtime_map[key]
        if not all_envs:
            manifest["environments"] = {
                key: value for key, value in environments.items() if key in runtime_map
            }
    manifest["format_version"] = 3
    manifest["python_abi"] = py_abi
    if runtime_map:
        manifest["runtime"] = runtime_map

(out_dir / "flashcli-bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"[pack] Wrote {out_dir / 'flashcli-bundle.json'}", file=sys.stderr)
PY

log "FlashHub upload dir: ${OUTPUT_DIR}"
