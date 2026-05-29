# Ensure a FlashRT source tree exists (clone or update unless caller overrides).
#
#   source scripts/lib/ensure_flashrt_repo.sh
#   ensure_flashrt_repo /path/to/FlashRT https://github.com/LiangSu8899/FlashRT.git main
#
# Exit 0 and print absolute REPO_ROOT on stdout (logs/git output go to stderr only).

_is_flashrt_repo() {
  [[ -f "$1/CMakeLists.txt" && -d "$1/flash_rt" ]]
}

_ensure_flashrt_log() {
  printf '[flashrt-repo] %s\n' "$*" >&2
}

_ensure_flashrt_die() {
  _ensure_flashrt_log "ERROR: $*"
  return 1
}

# Run git without polluting stdout (captured by callers via $(...)).
_ensure_git() {
  git "$@" >&2
}

# Clone or fetch+checkout FlashRT at dest from url @ ref.
ensure_flashrt_repo() {
  local dest="$1" url="$2" ref="$3"
  [[ -n "${dest}" && -n "${url}" && -n "${ref}" ]] || {
    _ensure_flashrt_die "ensure_flashrt_repo: dest, url, ref required"
    return 1
  }
  command -v git >/dev/null 2>&1 || {
    _ensure_flashrt_die "git not found (required to fetch FlashRT)"
    return 1
  }

  dest="$(cd "$(dirname "${dest}")" 2>/dev/null && pwd)/$(basename "${dest}")" || dest="$(realpath -m "${dest}" 2>/dev/null || echo "${dest}")"

  if [[ -d "${dest}/.git" ]]; then
    _ensure_flashrt_log "Updating ${dest} → ${ref}"
    _ensure_git -C "${dest}" fetch origin --tags --prune
    if ! _ensure_git -C "${dest}" checkout "${ref}" 2>/dev/null; then
      _ensure_git -C "${dest}" fetch origin "${ref}:${ref}" 2>/dev/null || true
      _ensure_git -C "${dest}" checkout "${ref}" || {
        _ensure_flashrt_die "Cannot checkout ${ref} in ${dest}"
        return 1
      }
    fi
    if git -C "${dest}" rev-parse --verify "origin/${ref}" >/dev/null 2>&1; then
      _ensure_git -C "${dest}" merge --ff-only "origin/${ref}" 2>/dev/null || true
    fi
  elif [[ -d "${dest}" ]]; then
    _ensure_flashrt_die "${dest} exists but is not a git repo (remove it or pass --repo-root elsewhere)"
    return 1
  else
    _ensure_flashrt_log "Cloning ${url} @ ${ref} → ${dest}"
    mkdir -p "$(dirname "${dest}")"
    if _ensure_git clone --depth 1 --branch "${ref}" --single-branch "${url}" "${dest}" 2>/dev/null; then
      :
    elif _ensure_git clone "${url}" "${dest}"; then
      _ensure_git -C "${dest}" checkout "${ref}" || {
        _ensure_flashrt_die "Cloned ${url} but cannot checkout ${ref}"
        return 1
      }
    else
      _ensure_flashrt_die "git clone failed: ${url}"
      return 1
    fi
  fi

  _is_flashrt_repo "${dest}" || {
    _ensure_flashrt_die "Not a FlashRT tree after checkout: ${dest} (need CMakeLists.txt + flash_rt/)"
    return 1
  }

  local head
  head="$(git -C "${dest}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  _ensure_flashrt_log "Ready: ${dest} @ ${ref} (${head})"
  printf '%s\n' "${dest}"
  return 0
}

# Use an existing local tree; optionally checkout ref when user passed --flashrt-ref.
ensure_flashrt_local_repo() {
  local dest="$1" ref="${2:-}"
  [[ -n "${dest}" ]] || {
    _ensure_flashrt_die "ensure_flashrt_local_repo: dest required"
    return 1
  }
  [[ -d "${dest}" ]] || {
    _ensure_flashrt_die "FlashRT path not found: ${dest}"
    return 1
  }
  dest="$(cd "${dest}" && pwd)"

  if [[ -n "${ref}" && -d "${dest}/.git" ]]; then
    _ensure_flashrt_log "Local repo ${dest} → checkout ${ref}"
    _ensure_git -C "${dest}" fetch origin --tags --prune 2>/dev/null || true
    _ensure_git -C "${dest}" checkout "${ref}" || {
      _ensure_flashrt_die "Cannot checkout ${ref} in ${dest}"
      return 1
    }
  fi

  _is_flashrt_repo "${dest}" || {
    _ensure_flashrt_die "Invalid FlashRT repo: ${dest}"
    return 1
  }

  _ensure_flashrt_log "Using local FlashRT: ${dest}"
  printf '%s\n' "${dest}"
  return 0
}
