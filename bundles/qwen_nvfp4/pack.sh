#!/usr/bin/env bash
# Pack qwen_nvfp4 for FlashHub / local run (wan22 + pi05_libero_nexus style).
#
# Beyond scripts/pack_bundle.sh:
#   1. Mirror lib/*.so → runtime/<env-key>/ when needed
#   2. Ensure flash_rt/BUNDLE_VERSION (FlashRT commit lock)
#   3. Auto --skip-matrix-verify when staged cells ≠ release-matrix.env
#      (e.g. local SM121 / aarch64 GB10 builds)
#   4. Post-check: dist has BUNDLE_VERSION, runtime cells, build.git_commit
#   5. Print validate / pull / run / serve commands for dist/
#
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${BUNDLE_DIR}/../.." && pwd)"
# shellcheck source=../../scripts/lib/native_naming.sh
source "${FLASHCLI_ROOT}/scripts/lib/native_naming.sh"
# shellcheck source=../../scripts/lib/load_release_matrix.sh
source "${FLASHCLI_ROOT}/scripts/lib/load_release_matrix.sh"

log() { printf '[qwen-pack] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

REPO_ROOT="${FLASHRT_REPO:-}"
OUTPUT_DIR=""
FORCE_SKIP_MATRIX=0
PACK_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      PACK_ARGS+=(--repo-root "$2")
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      PACK_ARGS+=(--output-dir "$2")
      shift 2
      ;;
    --skip-matrix-verify)
      FORCE_SKIP_MATRIX=1
      PACK_ARGS+=(--skip-matrix-verify)
      shift
      ;;
    -h|--help)
      cat <<EOF
Pack qwen_nvfp4 into dist/ (runnable FlashHub tree).

Usage:
  bash bundles/qwen_nvfp4/pack.sh [--repo-root DIR] [--output-dir DIR] [--skip-matrix-verify]

Prereq: bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT
EOF
      exit 0
      ;;
    *)
      PACK_ARGS+=("$1")
      shift
      ;;
  esac
done

[[ -f "${BUNDLE_DIR}/flashcli-bundle.json" ]] || die "Missing flashcli-bundle.json"
[[ -d "${BUNDLE_DIR}/flash_rt" ]] || die "Missing flash_rt/ (run build.sh first)"

load_release_matrix_config "${BUNDLE_DIR}" || die "Invalid release-matrix.env"

is_flashrt_repo() { [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]; }

resolve_repo_root() {
  if [[ -n "${REPO_ROOT}" ]]; then
    REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
    is_flashrt_repo "${REPO_ROOT}" || die "Invalid FlashRT repo: ${REPO_ROOT}"
    return 0
  fi
  local candidate
  for candidate in \
    "$(cd "${FLASHCLI_ROOT}/.." && pwd)" \
    "$(cd "${FLASHCLI_ROOT}/../.." && pwd)" \
    /app/FlashRT; do
    if [[ -d "${candidate}" ]] && is_flashrt_repo "${candidate}"; then
      REPO_ROOT="${candidate}"
      log "FlashRT repo: ${REPO_ROOT} (auto-detected)"
      return 0
    fi
  done
  return 1
}

# ── 1. Mirror lib/*.so → runtime/<env-key>/ ─────────────────────────────────
stage_runtime_from_lib() {
  local lib_dir="${BUNDLE_DIR}/lib"
  [[ -d "${lib_dir}" ]] || return 0
  shopt -s nullglob
  local -a sos=( "${lib_dir}"/*.so )
  shopt -u nullglob
  [[ ${#sos[@]} -gt 0 ]] || return 0

  python3 - "${BUNDLE_DIR}" "${FLASHCLI_ROOT}" <<'PY'
import shutil
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
flashcli_root = Path(sys.argv[2])
sys.path.insert(0, str(flashcli_root / "scripts" / "lib"))
from flashcli_bundle_path import ensure_flashcli_bundle_on_path

ensure_flashcli_bundle_on_path(flashcli_root)
from flashcli_bundle.native_naming import parse_native_tag_from_filename

lib = bundle / "lib"
cells: dict[str, list[Path]] = {}
for so in sorted(lib.glob("*.so")):
    parsed = parse_native_tag_from_filename(so.name)
    if parsed is None:
        print(f"[qwen-pack] WARN: skip unparseable {so.name}", file=sys.stderr)
        continue
    cells.setdefault(parsed.catalog_key(), []).append(so)

for key, paths in sorted(cells.items()):
    dest = bundle / "runtime" / key
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        shutil.copy2(p, dest / p.name)
    print(f"[qwen-pack] runtime/{key} ({len(paths)} .so)", file=sys.stderr)
PY
}

# ── 2. Ensure flash_rt/BUNDLE_VERSION ───────────────────────────────────────
ensure_bundle_version() {
  local bv="${BUNDLE_DIR}/flash_rt/BUNDLE_VERSION"
  if [[ -f "${bv}" ]]; then
    log "flash_rt/BUNDLE_VERSION present"
    return 0
  fi
  resolve_repo_root || die "Missing flash_rt/BUNDLE_VERSION and no FlashRT repo (pass --repo-root)"
  local git_commit git_short flashrt_tag flashrt_abi
  git_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
  git_short="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  flashrt_tag="$(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo dev)"
  flashrt_abi="$(sanitize_flashrt_abi "${flashrt_tag}" "${git_commit}")"
  cat > "${bv}" <<EOF
flashrt_commit=${git_commit}
flashrt_commit_short=${git_short}
flashrt_tag=${flashrt_tag}
flashrt_abi=${flashrt_abi}
source_repo=${REPO_ROOT}
built_at=$(date -u +%FT%TZ)
repaired_by=pack.sh
EOF
  log "Wrote flash_rt/BUNDLE_VERSION from ${REPO_ROOT} (${git_short})"
}

# ── 3. Decide whether release-matrix verify can pass ────────────────────────
need_skip_matrix_verify() {
  [[ "${FORCE_SKIP_MATRIX}" -eq 1 ]] && return 0
  local matrix_sm="${RELEASE_MATRIX_SM:-120}"
  local cuda_tags="${RELEASE_MATRIX_CUDA_TAGS:-130}"
  local py="${RELEASE_PYTHON_ABI:-312}"
  local arch
  arch="$(uname -m)"
  case "${arch}" in amd64|x64) arch="x86_64" ;; esac
  local expected="sm${matrix_sm}-cu${cuda_tags%% *}-linux-x86_64-py${py}"

  local has_expected=0 has_other=0
  shopt -s nullglob
  local cell
  for cell in "${BUNDLE_DIR}/runtime"/*/; do
    [[ -d "${cell}" ]] || continue
    local name
    name="$(basename "${cell}")"
    if compgen -G "${cell}"*.so >/dev/null 2>&1; then
      if [[ "${name}" == "${expected}" ]]; then
        has_expected=1
      else
        has_other=1
      fi
    fi
  done
  shopt -u nullglob

  # Official release cell missing, or only host-local cells (sm121/aarch64, …)
  if [[ "${has_expected}" -eq 0 && "${has_other}" -eq 1 ]]; then
    return 0
  fi
  if [[ "${arch}" != "x86_64" ]]; then
    return 0
  fi
  return 1
}

stage_runtime_from_lib
ensure_bundle_version

if need_skip_matrix_verify; then
  if [[ "${FORCE_SKIP_MATRIX}" -eq 0 ]]; then
    log "Staged runtime cells ≠ release-matrix (SM${RELEASE_MATRIX_SM}/x86_64); auto --skip-matrix-verify"
    PACK_ARGS+=(--skip-matrix-verify)
  fi
fi

# Ensure pack_bundle can resolve FlashRT when overlay/repair needs it.
if [[ -n "${REPO_ROOT}" ]]; then
  :
elif resolve_repo_root; then
  PACK_ARGS+=(--repo-root "${REPO_ROOT}")
fi

bash "${FLASHCLI_ROOT}/scripts/pack_bundle.sh" --bundle-dir "${BUNDLE_DIR}" "${PACK_ARGS[@]}"

[[ -n "${OUTPUT_DIR}" ]] || OUTPUT_DIR="${BUNDLE_DIR}/dist"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"

# ── 4. Post-pack runnable checks ────────────────────────────────────────────
[[ -f "${OUTPUT_DIR}/flashcli-bundle.json" ]] || die "dist missing flashcli-bundle.json"
[[ -f "${OUTPUT_DIR}/flash_rt/BUNDLE_VERSION" ]] || die "dist missing flash_rt/BUNDLE_VERSION"
[[ -d "${OUTPUT_DIR}/flash_rt" ]] || die "dist missing flash_rt/"
[[ -f "${OUTPUT_DIR}/run.py" && -f "${OUTPUT_DIR}/serve.py" ]] || die "dist missing run.py/serve.py"

python3 - "${OUTPUT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

dist = Path(sys.argv[1])
manifest = json.loads((dist / "flashcli-bundle.json").read_text())
runtime = manifest.get("runtime") or {}
if not runtime:
    print("[qwen-pack] ERROR: dist manifest runtime map empty", file=sys.stderr)
    sys.exit(1)
build = manifest.get("build") or {}
commit = str(build.get("git_commit") or "").strip()
missing = []
for key, rel in runtime.items():
    cell = dist / str(rel).lstrip("/")
    sos = list(cell.glob("flash_rt_kernels*.so")) if cell.is_dir() else []
    if not sos:
        missing.append(key)
if missing:
    print(f"[qwen-pack] ERROR: missing kernels in runtime cells: {missing}", file=sys.stderr)
    sys.exit(1)
bv = (dist / "flash_rt" / "BUNDLE_VERSION").read_text()
print(f"[qwen-pack] runtime cells: {', '.join(sorted(runtime))}", file=sys.stderr)
print(f"[qwen-pack] build.git_commit: {commit or '(none — check .build overlay)'}", file=sys.stderr)
print(f"[qwen-pack] BUNDLE_VERSION:\n{bv}", file=sys.stderr)
if commit and f"flashrt_commit={commit}" not in bv and commit[:12] not in bv:
    print(
        "[qwen-pack] WARN: BUNDLE_VERSION commit may not match build.git_commit; "
        "rebuild with the same FlashRT checkout",
        file=sys.stderr,
    )
PY

log "dist ready (runnable): ${OUTPUT_DIR}"
log "  flashcli bundle validate ${OUTPUT_DIR}"
log "  flashcli pull ${OUTPUT_DIR}@qwen3"
log "  flashcli run  ${OUTPUT_DIR}@qwen3 --prompt '你好' --max-tokens 64"
log "  flashcli serve ${OUTPUT_DIR}@qwen36 --host 0.0.0.0 --port 7631 --K 6"
