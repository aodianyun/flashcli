#!/usr/bin/env bash
# Run a long command in the background with local logging and optional auto-restart.
#
# Usage:
#   bash scripts/run_bg.sh --name release-pi05 -- \
#     bash scripts/release_bundle.sh --bundle pi05_libero --clean
#
#   bash scripts/run_bg.sh --name release-pi05 --status
#   bash scripts/run_bg.sh --name release-pi05 --tail
#   bash scripts/run_bg.sh --name release-pi05 --wait
#   bash scripts/run_bg.sh --name release-pi05 --stop
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=lib/release_docker_state.sh
source "${SCRIPT_DIR}/lib/release_docker_state.sh"

NAME=""
LOG_DIR="${FLASHCLI_ROOT}/logs"
LOG_FILE=""
CWD="${FLASHCLI_ROOT}"
ACTION="start"
MAX_RETRIES=3
RETRY_INTERVAL=3

log() { printf '[run-bg] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Run a command in the background; stdout/stderr go to a log file.

Usage:
  bash scripts/run_bg.sh --name JOB [OPTIONS] -- COMMAND [ARGS...]
  bash scripts/run_bg.sh --name JOB --status|--tail|--wait|--stop

Start options:
  --name NAME           Job id (required); used for .pid / .meta under logs/
  --log-dir DIR         Log directory (default: flashcli/logs)
  --log-file PATH       Explicit log path (default: logs/NAME-YYYYMMDD-HHMMSS.log)
  --cwd DIR             Working directory for COMMAND (default: flashcli root)
  --max-retries N       Restart up to N times after non-zero exit (default: 3; 0 = no restart)
  --retry-interval SEC  Seconds between restart attempts (default: 3)

Manage options (no COMMAND):
  --status              Print pid / running state / log path
  --tail                Follow the job log (tail -f)
  --wait                Block until the job exits; print exit code
  --stop                Stop supervisor and child process tree

Examples:
  bash scripts/run_bg.sh --name release-pi05 -- \
    bash scripts/release_bundle.sh --bundle pi05_libero --clean

  bash scripts/run_bg.sh --name release-qwen -- \
    bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean

  bash scripts/run_bg.sh --name release-pi05 --tail
EOF
}

pid_file() { printf '%s/%s.pid\n' "${LOG_DIR}" "${NAME}"; }
meta_file() { printf '%s/%s.meta\n' "${LOG_DIR}" "${NAME}"; }
stop_file() { printf '%s/%s.stop\n' "${LOG_DIR}" "${NAME}"; }

read_meta() {
  local key="$1" file
  file="$(meta_file)"
  [[ -f "${file}" ]] || return 1
  sed -n "s/^${key}=//p" "${file}" | tail -1
}

is_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

kill_process_tree() {
  local pid="$1" sig="${2:-TERM}"
  local children child

  [[ -z "${pid}" ]] && return 0
  children="$(pgrep -P "${pid}" 2>/dev/null || true)"
  for child in ${children}; do
    kill_process_tree "${child}" "${sig}"
  done
  kill "-${sig}" "${pid}" 2>/dev/null || true
}

run_in_new_session() {
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@"
  else
    "$@"
  fi
}

append_meta() {
  local file
  file="$(meta_file)"
  {
    printf '%s\n' "$@"
  } >> "${file}"
}

load_cmd_from_meta() {
  local quoted
  quoted="$(read_meta CMD_QUOTED 2>/dev/null || true)"
  [[ -n "${quoted}" ]] || die "CMD_QUOTED missing in $(meta_file)"
  printf '%s' "${quoted}"
}

cmd_supervisor_internal() {
  [[ -n "${NAME}" ]] || die "--name is required for supervisor"

  local stop_path cwd max_retries retry_interval attempt=0 child_pid=0 ec=0 cmd_quoted

  stop_path="$(stop_file)"
  cwd="$(read_meta CWD)"
  max_retries="$(read_meta MAX_RETRIES)"
  retry_interval="$(read_meta RETRY_INTERVAL)"
  cmd_quoted="$(load_cmd_from_meta)"
  # shellcheck disable=SC2086
  eval "set -- ${cmd_quoted}"

  rm -f "${stop_path}"

  _supervisor_cleanup() {
    if (( child_pid != 0 )) && is_running "${child_pid}"; then
      kill_process_tree "${child_pid}" TERM
    fi
    release_docker_stop_all "${FLASHCLI_ROOT}"
    exit 143
  }
  trap _supervisor_cleanup TERM INT

  while (( attempt <= max_retries )); do
    if [[ -f "${stop_path}" ]]; then
      log "Stop requested; supervisor exiting"
      break
    fi

    if (( attempt > 0 )); then
      log "Restart ${attempt}/${max_retries} in ${retry_interval}s (previous exit ${ec})"
      sleep "${retry_interval}"
      if [[ -f "${stop_path}" ]]; then
        log "Stop requested during restart wait; supervisor exiting"
        break
      fi
    fi

    log "Run attempt $((attempt + 1))/$((max_retries + 1)): $*"
    set +e
    run_in_new_session bash -c 'cd "$1" && shift && exec "$@"' _ "${cwd}" "$@" &
    child_pid=$!
    append_meta \
      "WORKER_PID=${child_pid}" \
      "WORKER_PGID=$(ps -o pgid= -p "${child_pid}" 2>/dev/null | tr -d '[:space:]')"
    wait "${child_pid}"
    ec=$?
    child_pid=0
    set -e

    append_meta \
      "RUN_ATTEMPT=$((attempt + 1))" \
      "EXIT_CODE=${ec}" \
      "FINISHED=$(date -Iseconds 2>/dev/null || date)"

    if [[ -f "${stop_path}" ]]; then
      log "Stop requested; supervisor exiting"
      break
    fi

    if (( ec == 0 )); then
      log "Command exited 0; supervisor done"
      break
    fi

    if (( attempt >= max_retries )); then
      log "Command failed with exit ${ec}; no retries left"
      break
    fi

    attempt=$((attempt + 1))
  done

  rm -f "${stop_path}"
  exit "${ec}"
}

cmd_start() {
  [[ -n "${NAME}" ]] || die "--name is required"
  [[ $# -gt 0 ]] || die "COMMAND required after -- (or use --status/--tail/--wait/--stop)"

  mkdir -p "${LOG_DIR}"

  local pf existing_pid
  pf="$(pid_file)"
  if [[ -f "${pf}" ]]; then
    existing_pid="$(tr -d '[:space:]' < "${pf}")"
    if is_running "${existing_pid}"; then
      die "Job '${NAME}' already running (pid ${existing_pid}). Stop it first or pick another --name."
    fi
    log "Removing stale pid file for '${NAME}' (pid ${existing_pid} not running)"
    rm -f "${pf}"
  fi

  rm -f "$(stop_file)"

  if [[ -z "${LOG_FILE}" ]]; then
    LOG_FILE="${LOG_DIR}/${NAME}-$(date +%Y%m%d-%H%M%S).log"
  else
    LOG_FILE="$(cd "$(dirname "${LOG_FILE}")" && pwd)/$(basename "${LOG_FILE}")"
    mkdir -p "$(dirname "${LOG_FILE}")"
  fi

  CWD="$(cd "${CWD}" && pwd)"

  log "Starting '${NAME}' in ${CWD}"
  log "Command: $*"
  log "Log: ${LOG_FILE}"
  log "Auto-restart: up to ${MAX_RETRIES} retries every ${RETRY_INTERVAL}s on non-zero exit"

  local cmd_quoted
  printf -v cmd_quoted '%q ' "$@"

  {
    printf 'LOG_FILE=%s\n' "${LOG_FILE}"
    printf 'CWD=%s\n' "${CWD}"
    printf 'CMD_QUOTED=%s\n' "${cmd_quoted}"
    printf 'MAX_RETRIES=%s\n' "${MAX_RETRIES}"
    printf 'RETRY_INTERVAL=%s\n' "${RETRY_INTERVAL}"
    printf 'STARTED=%s\n' "$(date -Iseconds 2>/dev/null || date)"
  } > "$(meta_file)"

  run_in_new_session bash "${SCRIPT_DIR}/run_bg.sh" \
    --supervisor-internal \
    --name "${NAME}" \
    --log-dir "${LOG_DIR}" \
    >> "${LOG_FILE}" 2>&1 &

  local pid=$!
  printf '%s\n' "${pid}" > "${pf}"

  append_meta "PID=${pid}"

  ln -sfn "$(basename "${LOG_FILE}")" "${LOG_DIR}/${NAME}.latest.log"

  log "Started supervisor pid=${pid}"
  log "  status: bash scripts/run_bg.sh --name ${NAME} --status"
  log "  tail:   bash scripts/run_bg.sh --name ${NAME} --tail"
  log "  wait:   bash scripts/run_bg.sh --name ${NAME} --wait"
}

cmd_status() {
  [[ -n "${NAME}" ]] || die "--name is required"

  local pf pid log_path started cmd_line state
  pf="$(pid_file)"
  if [[ ! -f "${pf}" ]]; then
    log "Job '${NAME}': not started (no ${pf})"
    exit 1
  fi

  pid="$(tr -d '[:space:]' < "${pf}")"
  log_path="$(read_meta LOG_FILE 2>/dev/null || true)"
  started="$(read_meta STARTED 2>/dev/null || true)"
  cmd_line="$(read_meta CMD_QUOTED 2>/dev/null || true)"

  if is_running "${pid}"; then
    state="running"
  else
    state="stopped"
  fi

  local exit_code finished run_attempt max_retries
  exit_code="$(read_meta EXIT_CODE 2>/dev/null || true)"
  finished="$(read_meta FINISHED 2>/dev/null || true)"
  run_attempt="$(read_meta RUN_ATTEMPT 2>/dev/null || true)"
  max_retries="$(read_meta MAX_RETRIES 2>/dev/null || true)"

  printf 'name:    %s\n' "${NAME}"
  printf 'state:   %s\n' "${state}"
  printf 'pid:     %s\n' "${pid}"
  [[ -n "${started}" ]] && printf 'started: %s\n' "${started}"
  [[ -n "${finished}" ]] && printf 'finished: %s\n' "${finished}"
  [[ -n "${exit_code}" ]] && printf 'exit:    %s\n' "${exit_code}"
  [[ -n "${run_attempt}" ]] && printf 'attempt: %s\n' "${run_attempt}"
  [[ -n "${max_retries}" ]] && printf 'retries: %s max\n' "${max_retries}"
  [[ -n "${log_path}" ]] && printf 'log:     %s\n' "${log_path}"
  [[ -n "${cmd_line}" ]] && printf 'cmd:     %s\n' "${cmd_line}"

  [[ "${state}" == "running" ]]
}

cmd_tail() {
  [[ -n "${NAME}" ]] || die "--name is required"

  local log_path="${LOG_DIR}/${NAME}.latest.log"
  if [[ -L "${log_path}" ]]; then
    log_path="$(readlink -f "${log_path}" 2>/dev/null || readlink "${log_path}")"
    [[ "${log_path}" != /* ]] && log_path="${LOG_DIR}/${log_path}"
  fi
  if [[ ! -f "${log_path}" ]]; then
    log_path="$(read_meta LOG_FILE 2>/dev/null || true)"
  fi
  [[ -n "${log_path}" && -f "${log_path}" ]] || die "No log for job '${NAME}'"

  log "Tailing ${log_path}"
  exec tail -f "${log_path}"
}

cmd_wait() {
  [[ -n "${NAME}" ]] || die "--name is required"

  local pf pid exit_code finished
  pf="$(pid_file)"
  [[ -f "${pf}" ]] || die "Job '${NAME}' not started"

  pid="$(tr -d '[:space:]' < "${pf}")"
  if is_running "${pid}"; then
    log "Waiting for '${NAME}' (pid ${pid})..."
    while is_running "${pid}"; do
      sleep 2
    done
  else
    log "Job '${NAME}' already finished (pid ${pid})"
  fi

  exit_code="$(read_meta EXIT_CODE 2>/dev/null || true)"
  finished="$(read_meta FINISHED 2>/dev/null || true)"
  if [[ -n "${finished}" ]]; then
    log "Finished at ${finished}"
  fi
  if [[ -n "${exit_code}" ]]; then
    log "Job '${NAME}' exit code ${exit_code}"
    exit "${exit_code}"
  fi

  log "Job '${NAME}' finished (exit code unknown)"
  exit 0
}

cmd_stop() {
  [[ -n "${NAME}" ]] || die "--name is required"

  local pf pid stop_path
  pf="$(pid_file)"
  stop_path="$(stop_file)"
  [[ -f "${pf}" ]] || die "Job '${NAME}' not started"

  pid="$(tr -d '[:space:]' < "${pf}")"
  if ! is_running "${pid}"; then
    log "Job '${NAME}' not running (pid ${pid}); cleaning up release containers"
    release_docker_stop_all "${FLASHCLI_ROOT}"
    rm -f "${pf}" "${stop_path}"
    exit 0
  fi

  log "Stopping '${NAME}' (supervisor pid ${pid})..."
  : > "${stop_path}"

  release_docker_stop_all "${FLASHCLI_ROOT}"

  local worker_pgid worker_pid
  worker_pid="$(read_meta WORKER_PID 2>/dev/null || true)"
  worker_pgid="$(read_meta WORKER_PGID 2>/dev/null || true)"
  if [[ -n "${worker_pgid}" && "${worker_pgid}" != "$$" ]]; then
    kill -TERM "-${worker_pgid}" 2>/dev/null || true
  fi
  if [[ -n "${worker_pid}" ]]; then
    kill_process_tree "${worker_pid}" TERM
  fi
  kill_process_tree "${pid}" TERM

  local i
  for i in $(seq 1 20); do
    is_running "${pid}" || break
    sleep 0.5
  done

  if is_running "${pid}"; then
    log "Still running; sending SIGKILL to process tree"
    if [[ -n "${worker_pgid}" && "${worker_pgid}" != "$$" ]]; then
      kill -KILL "-${worker_pgid}" 2>/dev/null || true
    fi
    [[ -n "${worker_pid}" ]] && kill_process_tree "${worker_pid}" KILL
    kill_process_tree "${pid}" KILL
    for i in $(seq 1 10); do
      is_running "${pid}" || break
      sleep 0.5
    done
  fi

  release_docker_stop_all "${FLASHCLI_ROOT}"

  rm -f "${pf}" "${stop_path}"
  log "Stopped '${NAME}'"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --log-file) LOG_FILE="$2"; shift 2 ;;
    --cwd) CWD="$2"; shift 2 ;;
    --max-retries) MAX_RETRIES="$2"; shift 2 ;;
    --retry-interval) RETRY_INTERVAL="$2"; shift 2 ;;
    --supervisor-internal) ACTION=supervisor; shift ;;
    --status) ACTION=status; shift ;;
    --tail) ACTION=tail; shift ;;
    --wait) ACTION=wait; shift ;;
    --stop|--kill) ACTION=stop; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    *)
      if [[ "${ACTION}" == "start" && -n "${NAME}" ]]; then
        break
      fi
      die "Unknown option: $1 (use --help)"
      ;;
  esac
done

case "${ACTION}" in
  start) cmd_start "$@" ;;
  supervisor) cmd_supervisor_internal "$@" ;;
  status) cmd_status ;;
  tail) cmd_tail ;;
  wait) cmd_wait ;;
  stop) cmd_stop ;;
esac
