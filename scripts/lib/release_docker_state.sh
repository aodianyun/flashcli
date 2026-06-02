# Track and stop flashcli release Docker containers (used by release_bundle.sh + run_bg.sh).
#
# State file lists container names started by release_bundle.sh. run_bg --stop
# reads it because docker run -d containers are not children of the worker process.

release_docker_state_file() {
  local root="${1:-${FLASHCLI_ROOT:-.}}"
  printf '%s/.release-docker.containers\n' "${root}"
}

release_docker_state_register() {
  local container="$1" state_file="${2:-}"
  [[ -n "${container}" ]] || return 0
  [[ -n "${state_file}" ]] || state_file="$(release_docker_state_file "${FLASHCLI_ROOT:-.}")"
  mkdir -p "$(dirname "${state_file}")"
  if [[ ! -f "${state_file}" ]] || ! grep -qxF "${container}" "${state_file}" 2>/dev/null; then
    printf '%s\n' "${container}" >> "${state_file}"
  fi
}

release_docker_state_unregister() {
  local container="$1" state_file="${2:-}" tmp
  [[ -n "${container}" ]] || return 0
  [[ -n "${state_file}" ]] || state_file="$(release_docker_state_file "${FLASHCLI_ROOT:-.}")"
  [[ -f "${state_file}" ]] || return 0
  tmp="$(mktemp)"
  grep -vxF "${container}" "${state_file}" > "${tmp}" 2>/dev/null || true
  mv "${tmp}" "${state_file}"
  [[ -s "${state_file}" ]] || rm -f "${state_file}"
}

release_docker_stop_container() {
  local container="$1"
  [[ -n "${container}" ]] || return 0
  command -v docker >/dev/null 2>&1 || return 0
  docker stop -t 5 "${container}" 2>/dev/null \
    || docker kill "${container}" 2>/dev/null \
    || true
  docker rm -f "${container}" 2>/dev/null || true
}

release_docker_stop_all() {
  local flashcli_root="${1:-${FLASHCLI_ROOT:-.}}" state_file container ids log_fn
  log_fn() { :; }
  if declare -F log >/dev/null 2>&1; then
    log_fn() { log "$@"; }
  fi

  command -v docker >/dev/null 2>&1 || return 0

  state_file="$(release_docker_state_file "${flashcli_root}")"
  if [[ -f "${state_file}" ]]; then
    while IFS= read -r container || [[ -n "${container}" ]]; do
      [[ -n "${container}" ]] || continue
      log_fn "Stopping release container ${container}..."
      release_docker_stop_container "${container}"
    done < "${state_file}"
    rm -f "${state_file}"
  fi

  ids="$(docker ps -q --filter name=flashcli-release- 2>/dev/null || true)"
  if [[ -n "${ids}" ]]; then
    log_fn "Stopping flashcli-release-* containers..."
    # shellcheck disable=SC2086
    docker stop -t 5 ${ids} 2>/dev/null || docker kill ${ids} 2>/dev/null || true
    # shellcheck disable=SC2086
    docker rm -f ${ids} 2>/dev/null || true
  fi

  pkill -TERM -f 'docker (wait|logs -f) flashcli-release-' 2>/dev/null || true
}
