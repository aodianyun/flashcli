#!/usr/bin/env bash
# Vendor Isaac-GR00T inference-only gr00t/ package into the bundle root.
# No pip install — activate_bundle PYTHONPATH resolves import gr00t.
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${BUNDLE_DIR}/gr00t"
VENDOR_META="${DEST}/VENDOR.json"

GR00T_REPO="${GR00T_REPO:-https://github.com/NVIDIA/Isaac-GR00T.git}"
GR00T_REF="${GR00T_REF:-ab88b50c718f6528e1df9dcbaf75865d1b604760}"

log() { printf '[vendor-gr00t] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

git_clone_url() {
  local repo_url="$1"
  local proxy="${FLASHCLI_GIT_PROXY:-}"
  proxy="${proxy%/}"
  case "${proxy}" in
    ""|0|false|no|off|FALSE|NO|OFF) printf '%s' "${repo_url}"; return ;;
  esac
  if [[ "${repo_url}" == "${proxy}/"* ]]; then
    printf '%s' "${repo_url}"
    return
  fi
  printf '%s/%s' "${proxy}" "${repo_url}"
}

resolve_source_dir() {
  local local_src="${FLASHCLI_GR00T_SRC:-}"
  if [[ -n "${local_src}" ]]; then
    local_src="$(cd "${local_src}" && pwd)"
    [[ -d "${local_src}/gr00t" ]] || die "FLASHCLI_GR00T_SRC must contain gr00t/: ${local_src}"
    printf '%s' "${local_src}"
    return
  fi

  local cache_root="${FLASHCLI_HOME:-${HOME}/.flashcli}/cache/isaac-gr00t-src"
  local safe_ref="${GR00T_REF//[^A-Za-z0-9._-]/_}"
  local cache_dir="${cache_root}/${safe_ref}"

  if [[ -f "${cache_dir}/pyproject.toml" && -d "${cache_dir}/gr00t" ]]; then
    printf '%s' "${cache_dir}"
    return
  fi

  command -v git >/dev/null 2>&1 || die "git not found (required to vendor gr00t)"
  local clone_url
  clone_url="$(git_clone_url "${GR00T_REPO}")"
  mkdir -p "${cache_root}"
  if [[ -e "${cache_dir}" ]]; then
    rm -rf "${cache_dir}"
  fi
  log "Cloning Isaac-GR00T ref ${GR00T_REF} (no submodules) -> ${cache_dir}"
  git clone --filter=blob:none --no-recurse-submodules --depth 1 "${clone_url}" "${cache_dir}"
  git -C "${cache_dir}" fetch --depth 1 origin "${GR00T_REF}"
  git -C "${cache_dir}" checkout FETCH_HEAD
  printf '%s' "${cache_dir}"
}

prune_vendor_tree() {
  local root="$1"
  local -a prune_dirs=(
    "__pycache__"
    ".pytest_cache"
    ".mypy_cache"
  )
  local pat
  for pat in "${prune_dirs[@]}"; do
    find "${root}" -type d -name "${pat}" -prune -exec rm -rf {} + 2>/dev/null || true
  done
  find "${root}" -type f -name '*.pyc' -delete 2>/dev/null || true
}

write_vendor_meta() {
  local src_root="$1"
  local commit
  commit="$(git -C "${src_root}" rev-parse HEAD 2>/dev/null || echo unknown)"
  python3 - "${VENDOR_META}" "${GR00T_REPO}" "${GR00T_REF}" "${commit}" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, repo, ref, commit = sys.argv[1:5]
payload = {
    "package": "gr00t",
    "source": "isaac-gr00t-vendor",
    "repo": repo,
    "git_ref": ref,
    "commit": commit,
    "vendored_at": datetime.now(timezone.utc).isoformat(),
    "excluded_paths": [
        "external_dependencies",
        "scripts/deployment",
        "tests",
    ],
    "install": "none — import via bundle PYTHONPATH",
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY
}

main() {
  local src_root
  src_root="$(resolve_source_dir)"
  [[ -d "${src_root}/gr00t" ]] || die "Missing gr00t/ in ${src_root}"

  rm -rf "${DEST}"
  mkdir -p "${DEST}"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude='__pycache__/' \
      --exclude='*.pyc' \
      --exclude='.pytest_cache/' \
      "${src_root}/gr00t/" "${DEST}/"
  else
    cp -a "${src_root}/gr00t/." "${DEST}/"
    prune_vendor_tree "${DEST}"
  fi

  if [[ -f "${src_root}/LICENSE" ]]; then
    cp -f "${src_root}/LICENSE" "${DEST}/THIRD_PARTY_LICENSE"
  elif [[ -f "${src_root}/LICENSE.txt" ]]; then
    cp -f "${src_root}/LICENSE.txt" "${DEST}/THIRD_PARTY_LICENSE"
  else
    log "WARN: LICENSE not found in ${src_root}; skipping THIRD_PARTY_LICENSE"
  fi

  write_vendor_meta "${src_root}"
  prune_vendor_tree "${DEST}"

  [[ -f "${DEST}/policy/gr00t_policy.py" ]] || die "Vendored tree missing policy/gr00t_policy.py"
  [[ -d "${DEST}/model/gr00t_n1d7" ]] || die "Vendored tree missing model/gr00t_n1d7/"
  log "Vendored gr00t -> ${DEST} (commit $(python3 -c "import json; print(json.load(open('${VENDOR_META}'))['commit'][:12])"))"
}

main "$@"
