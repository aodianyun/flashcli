#!/usr/bin/env bash
# Run a long command in the background with local logging.
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

NAME=""
LOG_DIR="${FLASHCLI_ROOT}/logs"
LOG_FILE=""
CWD="${FLASHCLI_ROOT}"
ACTION="start"

log() { printf '[run-bg] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Run a command in the background; stdout/stderr go to a log file.

Usage:
  bash scripts/run_bg.sh --name JOB [OPTIONS] -- COMMAND [ARGS...]
  bash scripts/run_bg.sh --name JOB --status|--tail|--wait|--stop

Start options:
  --name NAME       Job id (required); used for .pid / .meta under logs/
  --log-dir DIR     Log directory (default: flashcli/logs)
  --log-file PATH   Explicit log path (default: logs/NAME-YYYYMMDD-HHMMSS.log)
  --cwd DIR         Working directory for COMMAND (default: flashcli root)

Manage options (no COMMAND):
  --status          Print pid / running state / log path
  --tail            Follow the job log (tail -f)
  --wait            Block until the job exits; print exit code
  --stop            Send SIGTERM, then SIGKILL after 10s if still alive

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

read_meta() {
  local key="$1" file
  file="$(meta_file)"
  [[ -f "${file}" ]] || return 1
  sed -n "s/^${key}=//p" "${file}" | head -1
}

is_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
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

  (
    cd "${CWD}"
    set +e
    "$@"
    ec=$?
    {
      printf 'EXIT_CODE=%s\n' "${ec}"
      printf 'FINISHED=%s\n' "$(date -Iseconds 2>/dev/null || date)"
    } >> "$(meta_file)"
    exit "${ec}"
  ) >> "${LOG_FILE}" 2>&1 &

  local pid=$!
  printf '%s\n' "${pid}" > "${pf}"

  {
    printf 'LOG_FILE=%s\n' "${LOG_FILE}"
    printf 'PID=%s\n' "${pid}"
    printf 'STARTED=%s\n' "$(date -Iseconds 2>/dev/null || date)"
    printf 'CWD=%s\n' "${CWD}"
    printf 'CMD=%s\n' "$*"
  } > "$(meta_file)"

  ln -sfn "$(basename "${LOG_FILE}")" "${LOG_DIR}/${NAME}.latest.log"

  log "Started pid=${pid}"
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
  cmd_line="$(read_meta CMD 2>/dev/null || true)"

  if is_running "${pid}"; then
    state="running"
  else
    state="stopped"
  fi

  local exit_code finished
  exit_code="$(read_meta EXIT_CODE 2>/dev/null || true)"
  finished="$(read_meta FINISHED 2>/dev/null || true)"

  printf 'name:    %s\n' "${NAME}"
  printf 'state:   %s\n' "${state}"
  printf 'pid:     %s\n' "${pid}"
  [[ -n "${started}" ]] && printf 'started: %s\n' "${started}"
  [[ -n "${finished}" ]] && printf 'finished: %s\n' "${finished}"
  [[ -n "${exit_code}" ]] && printf 'exit:    %s\n' "${exit_code}"
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

  local pf pid
  pf="$(pid_file)"
  [[ -f "${pf}" ]] || die "Job '${NAME}' not started"

  pid="$(tr -d '[:space:]' < "${pf}")"
  if ! is_running "${pid}"; then
    log "Job '${NAME}' not running (pid ${pid})"
    rm -f "${pf}"
    exit 0
  fi

  log "Stopping '${NAME}' (pid ${pid})..."
  kill -TERM "${pid}" 2>/dev/null || true

  local i
  for i in $(seq 1 20); do
    is_running "${pid}" || break
    sleep 0.5
  done

  if is_running "${pid}"; then
    log "Still running; sending SIGKILL"
    kill -KILL "${pid}" 2>/dev/null || true
  fi

  log "Stopped '${NAME}'"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --log-file) LOG_FILE="$2"; shift 2 ;;
    --cwd) CWD="$2"; shift 2 ;;
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
  status) cmd_status ;;
  tail) cmd_tail ;;
  wait) cmd_wait ;;
  stop) cmd_stop ;;
esac
