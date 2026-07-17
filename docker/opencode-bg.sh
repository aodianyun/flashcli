#!/bin/bash
# Reliable one-click OpenCode manager for flashcli-bundle-build.
#
# Design (intentionally dumb):
#   - supervise loop = same idea as codeplan/runopencode.sh
#   - setsid + nohup so it survives shell exit / VNC disconnect
#   - flock prevents double-start
#   - stop kills the whole process group (supervisor + opencode)
#   - start waits until TCP port is open (not just pid alive)
#
#   opencode-bg          # start (default)
#   opencode-bg stop|restart|status|logs [-f]|fg|help

set -eu

PORT="${OPENCODE_PORT:-8080}"
HOST="${OPENCODE_HOST:-0.0.0.0}"
STATE_DIR="${OPENCODE_STATE_DIR:-/var/lib/opencode-web}"
LOG_FILE="${OPENCODE_LOG_FILE:-/var/log/opencode-web.log}"
PID_FILE="${OPENCODE_PID_FILE:-${STATE_DIR}/supervise.pid}"
LOCK_FILE="${OPENCODE_LOCK_FILE:-${STATE_DIR}/supervise.lock}"
SUPERVISE="${OPENCODE_SUPERVISE:-/usr/local/lib/flashcli/opencode-supervise}"

resolve_paths() {
  if ! mkdir -p "${STATE_DIR}" "$(dirname "${LOG_FILE}")" 2>/dev/null \
    || ! touch "${LOG_FILE}" "${LOCK_FILE}" 2>/dev/null; then
    STATE_DIR="${HOME}/.cache/opencode-web"
    LOG_FILE="${STATE_DIR}/opencode-web.log"
    PID_FILE="${STATE_DIR}/supervise.pid"
    LOCK_FILE="${STATE_DIR}/supervise.lock"
    mkdir -p "${STATE_DIR}"
    touch "${LOG_FILE}" "${LOCK_FILE}"
  fi
  export OPENCODE_PORT OPENCODE_HOST OPENCODE_LOG_FILE="${LOG_FILE}"
}

pid_alive() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

read_pid() {
  [[ -f "${PID_FILE}" ]] || return 1
  tr -d ' \n' <"${PID_FILE}"
}

is_running() {
  local pid
  pid="$(read_pid 2>/dev/null || true)"
  pid_alive "${pid}"
}

port_open() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -qE ":${PORT}\\b"
    return $?
  fi
  (echo >/dev/tcp/127.0.0.1/"${PORT}") >/dev/null 2>&1
}

wait_port() {
  local i
  for i in $(seq 1 50); do
    if port_open; then
      return 0
    fi
    if ! is_running; then
      return 1
    fi
    sleep 0.2
  done
  return 1
}

start_bg() {
  resolve_paths

  if is_running && port_open; then
    echo "OpenCode already running (pid=$(read_pid), :${PORT})"
    echo "  logs: opencode-bg logs -f"
    return 0
  fi

  if is_running && ! port_open; then
    echo "stale/half-dead supervisor; stopping first..."
    stop_bg || true
  fi

  if [[ ! -x "${SUPERVISE}" ]]; then
    echo "ERROR: missing supervise script: ${SUPERVISE}" >&2
    return 1
  fi

  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    echo "ERROR: another opencode-bg start is in progress" >&2
    return 1
  fi

  rm -f "${PID_FILE}"
  setsid "${SUPERVISE}" </dev/null >>"${LOG_FILE}" 2>&1 &
  echo $! >"${PID_FILE}"
  flock -u 9 || true

  if ! wait_port; then
    echo "ERROR: OpenCode did not open :${PORT} in time" >&2
    echo "---- last log ----" >&2
    tail -n 50 "${LOG_FILE}" >&2 || true
    stop_bg >/dev/null 2>&1 || true
    return 1
  fi

  echo "OpenCode started (pid=$(read_pid), ${HOST}:${PORT})"
  echo "  UI:   http://<host>:${PORT}"
  echo "  logs: opencode-bg logs -f"
  echo "  stop: opencode-bg stop"
}

stop_bg() {
  resolve_paths
  local pid
  pid="$(read_pid 2>/dev/null || true)"

  if pid_alive "${pid}"; then
    kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
    local i
    for i in $(seq 1 20); do
      pid_alive "${pid}" || break
      sleep 0.1
    done
    if pid_alive "${pid}"; then
      kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi

  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
  fi

  rm -f "${PID_FILE}"
  echo "OpenCode stopped"
}

status_bg() {
  resolve_paths
  local pid
  pid="$(read_pid 2>/dev/null || true)"
  if pid_alive "${pid}"; then
    if port_open; then
      echo "running pid=${pid} listen=${HOST}:${PORT} log=${LOG_FILE}"
      return 0
    fi
    echo "degraded pid=${pid} (alive but :${PORT} not listening) log=${LOG_FILE}"
    return 1
  fi
  echo "stopped port=${PORT} log=${LOG_FILE}"
  return 1
}

logs_bg() {
  resolve_paths
  if [[ "${1:-}" == "-f" ]] || [[ "${1:-}" == "--follow" ]]; then
    tail -n 100 -f "${LOG_FILE}"
  else
    tail -n 100 "${LOG_FILE}"
  fi
}

fg_run() {
  resolve_paths
  echo "OpenCode foreground ${HOST}:${PORT}"
  exec opencode web --hostname "${HOST}" --port "${PORT}"
}

usage() {
  cat <<EOF
Usage: opencode-bg [start|stop|restart|status|logs [-f]|fg|help]

  start     background start + auto-restart (default)
  stop      stop supervisor and opencode
  restart   stop then start
  status    pid + listen check
  logs [-f] show / follow log
  fg        foreground (blocking)

Env: OPENCODE_PORT OPENCODE_HOST OPENCODE_LOG_FILE OPENCODE_STATE_DIR
EOF
}

main() {
  local action="${1:-start}"
  case "${action}" in
    start) start_bg ;;
    stop) stop_bg ;;
    restart) stop_bg; start_bg ;;
    status) status_bg ;;
    logs) shift || true; logs_bg "${1:-}" ;;
    fg|foreground) fg_run ;;
    help|-h|--help) usage ;;
    *)
      echo "Unknown action: ${action}" >&2
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
