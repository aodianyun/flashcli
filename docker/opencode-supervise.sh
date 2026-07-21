#!/bin/bash
# Restart loop only — launched by opencode-bg via setsid/nohup.
set -u
PORT="${OPENCODE_PORT:-8080}"
HOST="${OPENCODE_HOST:-0.0.0.0}"
LOG_FILE="${OPENCODE_LOG_FILE:-/var/log/opencode-web.log}"

mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true
touch "${LOG_FILE}" 2>/dev/null || true

while true; do
  echo "$(date -Is): starting opencode web ${HOST}:${PORT}" >>"${LOG_FILE}"
  opencode web --hostname "${HOST}" --port "${PORT}" >>"${LOG_FILE}" 2>&1
  code=$?
  echo "$(date -Is): exited code=${code}; restart in 5s" >>"${LOG_FILE}"
  sleep 5
done
