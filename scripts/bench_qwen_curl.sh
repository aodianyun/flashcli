#!/usr/bin/env bash
# HTTP benchmark for Qwen3 / Qwen36 via OpenAI-compatible /v1/chat/completions.
#
# Prerequisites: one or two HTTP servers (single-GPU: run one model at a time).
#   flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000
#   flashcli serve qwen36-27b-nvfp4 --host 0.0.0.0 --port 8001 --K 6
#
# Single GPU (only one serve process):
#   bash scripts/bench_qwen_curl.sh --qwen3-only
#   bash scripts/bench_qwen_curl.sh --qwen36-only --qwen36-long-tokens 32768
#
# Usage:
#   export CKPT_QWEN3=~/.flashcli/models/qwen3-8b-nvfp4/checkpoint
#   export CKPT_QWEN36=~/.flashcli/models/qwen36-27b-nvfp4/checkpoint
#   bash scripts/bench_qwen_curl.sh
#   bash scripts/bench_qwen_curl.sh --qwen36-long-tokens 131072 --qwen36-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MAKE_PAYLOAD="${SCRIPT_DIR}/bench_qwen_make_payload.py"

HOST="${HOST:-127.0.0.1}"
QWEN3_PORT="${QWEN3_PORT:-8000}"
QWEN36_PORT="${QWEN36_PORT:-8001}"
QWEN3_MODEL="${QWEN3_MODEL:-qwen3-8b-nvfp4}"
QWEN36_MODEL="${QWEN36_MODEL:-qwen3.6-27b-nvfp4}"

CKPT_QWEN3="${CKPT_QWEN3:-${HOME}/.flashcli/models/qwen3-8b-nvfp4/checkpoint}"
CKPT_QWEN36="${CKPT_QWEN36:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/checkpoint}"

SHORT_PROMPT="${SHORT_PROMPT:-用一段话介绍量子纠缠。}"
SHORT_MAX_TOKENS="${SHORT_MAX_TOKENS:-64}"
# Qwen3 default serve max_seq≈2048; leave room for generation.
QWEN3_LONG_PROMPT_TOKENS="${QWEN3_LONG_PROMPT_TOKENS:-1536}"
QWEN36_LONG_PROMPT_TOKENS="${QWEN36_LONG_PROMPT_TOKENS:-32768}"
LONG_MAX_TOKENS="${LONG_MAX_TOKENS:-64}"

SKIP_QWEN3=0
SKIP_QWEN36=0
SKIP_QWEN3_LONG=0
SKIP_QWEN36_LONG=0
SKIP_SHORT=0
WORKDIR="${WORKDIR:-/tmp/flashcli-bench-qwen-$$}"

usage() {
  cat <<EOF
Usage: bash scripts/bench_qwen_curl.sh [OPTIONS]

Runs short- and long-context curl tests against running Qwen HTTP servers.
Long prompts are built with bench_qwen_make_payload.py (~N tokens).

Options:
  --workdir DIR           Temp payloads (default: /tmp/flashcli-bench-qwen-PID)
  --qwen3-long-tokens N   Long prompt tokens for qwen3 (default: ${QWEN3_LONG_PROMPT_TOKENS})
  --qwen36-long-tokens N  Long prompt tokens for qwen36 (default: ${QWEN36_LONG_PROMPT_TOKENS})
  --short-max-tokens N    Decode length for short test (default: ${SHORT_MAX_TOKENS})
  --long-max-tokens N     Decode length for long test (default: ${LONG_MAX_TOKENS})
  --qwen3-only            Only bench qwen3 (single GPU: serve qwen3, then run this)
  --qwen36-only           Only bench qwen36 (single GPU: serve qwen36, then run this)
  --skip-qwen3-long       Skip qwen3 long (qwen3 is short-ctx only in FlashRT)
  --skip-qwen36-long      Skip qwen36 long prefill test
  --skip-short            Skip short tests
  -h, --help

Env: HOST, QWEN3_PORT, QWEN36_PORT, CKPT_QWEN3, CKPT_QWEN36, SHORT_PROMPT
EOF
}

log() { printf '[bench-qwen] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR="$2"; shift 2 ;;
    --qwen3-long-tokens) QWEN3_LONG_PROMPT_TOKENS="$2"; shift 2 ;;
    --qwen36-long-tokens) QWEN36_LONG_PROMPT_TOKENS="$2"; shift 2 ;;
    --short-max-tokens) SHORT_MAX_TOKENS="$2"; shift 2 ;;
    --long-max-tokens) LONG_MAX_TOKENS="$2"; shift 2 ;;
    --qwen3-only) SKIP_QWEN36=1; shift ;;
    --qwen36-only) SKIP_QWEN3=1; shift ;;
    --skip-qwen3-long) SKIP_QWEN3_LONG=1; shift ;;
    --skip-qwen36-long) SKIP_QWEN36_LONG=1; shift ;;
    --skip-short) SKIP_SHORT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ "${SKIP_QWEN3}" -eq 1 && "${SKIP_QWEN36}" -eq 1 ]]; then
  die "Cannot use both --qwen3-only and --qwen36-only"
fi

command -v curl >/dev/null 2>&1 || die "curl not found"
command -v jq >/dev/null 2>&1 || die "jq not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"
[[ -f "${MAKE_PAYLOAD}" ]] || die "Missing ${MAKE_PAYLOAD}"

mkdir -p "${WORKDIR}"

health() {
  local port="$1"
  curl -sf "http://${HOST}:${port}/health" >/dev/null 2>&1
}

make_short_payload() {
  local model="$1" out="$2"
  jq -n \
    --arg model "${model}" \
    --arg content "${SHORT_PROMPT}" \
    --argjson max_tokens "${SHORT_MAX_TOKENS}" \
    '{
      model: $model,
      messages: [{role: "user", content: $content}],
      max_tokens: $max_tokens,
      temperature: 0,
      stream: false
    }' >"${out}"
}

make_long_payload() {
  local ckpt="$1" model="$2" target_tokens="$3" out="$4"
  python3 "${MAKE_PAYLOAD}" \
    --checkpoint "${ckpt}" \
    --model "${model}" \
    --target-prompt-tokens "${target_tokens}" \
    --max-tokens "${LONG_MAX_TOKENS}" \
    --output "${out}"
}

# Print wall clock + usage fields (FlashRT + flashcli serve).
summarize() {
  local label="$1" resp="$2" wall_ms="$3"
  log "━━ ${label} (curl wall ${wall_ms} ms) ━━"
  if [[ ! -s "${resp}" ]]; then
    log "  empty response"
    return 1
  fi
  if jq -e '.error' "${resp}" >/dev/null 2>&1; then
    jq -r '.error | tostring' "${resp}" >&2
    return 1
  fi
  jq -r '
    .usage // {} |
    "  usage: " + (
      [
        (if .prompt_tokens != null then "prompt_tokens=\(.prompt_tokens)" else empty end),
        (if .completion_tokens != null then "completion_tokens=\(.completion_tokens)" else empty end),
        (if .prefill_ms != null then "prefill_ms=\(.prefill_ms)" else empty end),
        (if .decode_ms != null then "decode_ms=\(.decode_ms)" else empty end),
        (if .wall_s != null then "wall_s=\(.wall_s)" else empty end),
        (if .tok_per_s != null then "tok_per_s=\(.tok_per_s)" else empty end),
        (if .decode_tok_per_s != null then "decode_tok_per_s=\(.decode_tok_per_s)" else empty end),
        (if .e2e_tok_per_s != null then "e2e_tok_per_s=\(.e2e_tok_per_s)" else empty end)
      ] | join(" ")
    )
  ' "${resp}" 2>/dev/null || cat "${resp}" >&2
  local preview
  preview="$(jq -r '.choices[0].message.content // ""' "${resp}" 2>/dev/null | head -c 120)"
  if [[ -n "${preview}" ]]; then
    log "  text[0:120]: ${preview}…"
  fi
}

run_curl() {
  local label="$1" port="$2" payload="$3" resp="$4"
  local t0 t1 wall_ms
  t0="$(python3 -c 'import time; print(int(time.time()*1000))')"
  curl -sf "http://${HOST}:${port}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d @"${payload}" \
    -o "${resp}" \
    || die "${label}: curl failed (is serve running on :${port}?)"
  t1="$(python3 -c 'import time; print(int(time.time()*1000))')"
  wall_ms=$((t1 - t0))
  summarize "${label}" "${resp}" "${wall_ms}"
}

log "workdir=${WORKDIR}"
if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
  log "qwen3 → http://${HOST}:${QWEN3_PORT}  ckpt=${CKPT_QWEN3}"
fi
if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
  log "qwen36 → http://${HOST}:${QWEN36_PORT}  ckpt=${CKPT_QWEN36}"
fi

if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
  health "${QWEN3_PORT}" || die "qwen3 not healthy at :${QWEN3_PORT} (/health)"
fi
if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
  health "${QWEN36_PORT}" || die "qwen36 not healthy at :${QWEN36_PORT} (/health)"
fi

if [[ "${SKIP_SHORT}" -eq 0 ]]; then
  if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
    make_short_payload "${QWEN3_MODEL}" "${WORKDIR}/qwen3_short.json"
    run_curl "qwen3 short ctx" "${QWEN3_PORT}" \
      "${WORKDIR}/qwen3_short.json" "${WORKDIR}/qwen3_short.out.json"
  fi
  if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
    make_short_payload "${QWEN36_MODEL}" "${WORKDIR}/qwen36_short.json"
    run_curl "qwen36 short ctx" "${QWEN36_PORT}" \
      "${WORKDIR}/qwen36_short.json" "${WORKDIR}/qwen36_short.out.json"
  fi
fi

if [[ "${SKIP_QWEN3}" -eq 0 && "${SKIP_QWEN3_LONG}" -eq 0 ]]; then
  log "qwen3 long: target prompt_tokens=${QWEN3_LONG_PROMPT_TOKENS} (within ~2048 max_seq)"
  make_long_payload "${CKPT_QWEN3}" "${QWEN3_MODEL}" \
    "${QWEN3_LONG_PROMPT_TOKENS}" "${WORKDIR}/qwen3_long.json"
  run_curl "qwen3 long ctx (prompt≈${QWEN3_LONG_PROMPT_TOKENS})" "${QWEN3_PORT}" \
    "${WORKDIR}/qwen3_long.json" "${WORKDIR}/qwen3_long.out.json"
fi

if [[ "${SKIP_QWEN36}" -eq 0 && "${SKIP_QWEN36_LONG}" -eq 0 ]]; then
  log "qwen36 long: target prompt_tokens=${QWEN36_LONG_PROMPT_TOKENS} (prefill may take minutes)"
  make_long_payload "${CKPT_QWEN36}" "${QWEN36_MODEL}" \
    "${QWEN36_LONG_PROMPT_TOKENS}" "${WORKDIR}/qwen36_long.json"
  run_curl "qwen36 long ctx (prompt≈${QWEN36_LONG_PROMPT_TOKENS})" "${QWEN36_PORT}" \
    "${WORKDIR}/qwen36_long.json" "${WORKDIR}/qwen36_long.out.json"
fi

log "Done. Payloads and responses in ${WORKDIR}"
