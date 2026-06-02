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
#   bash scripts/bench_qwen_curl.sh --qwen3-only --rounds 5   # 5 runs, drop 1st, mean last 4
#   bash scripts/bench_qwen_curl.sh --qwen36-long-tokens 131072 --qwen36-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MAKE_PAYLOAD="${SCRIPT_DIR}/bench_qwen_make_payload.py"
STREAM_ONCE="${SCRIPT_DIR}/bench_qwen_curl_stream.py"
SERVE_METRICS_PY="${SCRIPT_DIR}/bench_qwen36_serve_metrics.py"

HOST="${HOST:-127.0.0.1}"
QWEN3_PORT="${QWEN3_PORT:-8000}"
QWEN36_PORT="${QWEN36_PORT:-8001}"
QWEN3_MODEL="${QWEN3_MODEL:-qwen3-8b-nvfp4}"
QWEN36_MODEL="${QWEN36_MODEL:-qwen3.6-27b-nvfp4}"

CKPT_QWEN3="${CKPT_QWEN3:-${HOME}/.flashcli/models/qwen3-8b-nvfp4/checkpoint}"
CKPT_QWEN36="${CKPT_QWEN36:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/checkpoint}"

SHORT_PROMPT="${SHORT_PROMPT:-Explain quantum entanglement in one short paragraph.}"
SHORT_MAX_TOKENS="${SHORT_MAX_TOKENS:-64}"
# Qwen3 HTTP API: prompt_tokens must be <= serve --max-q-seq (not just max-seq).
# Default 960 matches common serve --max-q-seq 1024 (+ 64 decode). For ~1536:
#   serve --max-q-seq 1984  &&  --qwen3-long-tokens 1536
# Cap long prompt to fit serve --max-q-seq. Unset → assume 1024. Set 0/off/none → no cap.
QWEN3_LONG_PROMPT_TOKENS="${QWEN3_LONG_PROMPT_TOKENS:-1536}"
QWEN36_LONG_PROMPT_TOKENS="${QWEN36_LONG_PROMPT_TOKENS:-32768}"
LONG_MAX_TOKENS="${LONG_MAX_TOKENS:-64}"

SKIP_QWEN3=0
SKIP_QWEN36=0
SKIP_QWEN3_LONG=0
SKIP_QWEN36_LONG=0
SKIP_SHORT=0
SKIP_PAYLOAD_BUILD=0
ROUNDS="${BENCH_ROUNDS:-1}"
SKIP_FIRST="${BENCH_SKIP_FIRST-}"
LONG_PROMPT_STYLE="${LONG_PROMPT_STYLE:-repeat}"
BENCH_PROFILE="${BENCH_PROFILE:-}"
BENCH_STREAM="${BENCH_STREAM:-1}"
WORKDIR="${WORKDIR:-/tmp/flashcli-bench-qwen-$$}"
SERVE_LOG_PATH="${SERVE_LOG_PATH:-${QWEN36_SERVE_LOG:-}}"
SERVE_LOG_BACKEND="${SERVE_LOG_BACKEND:-auto}"
WRITE_REPORT=0
REPORT_PY="${SCRIPT_DIR}/bench_qwen36_report.py"

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
  --skip-payload-build    Require qwen36_short.json (+ qwen36_long.json) already in --workdir
  --rounds N              Repeat each case N times (default: ${ROUNDS})
  --skip-first K          Drop first K rounds before averaging (default: 1 if rounds>1)
  --long-prompt-style S   repeat | flashrt | doc (flashrt=FlashRT doc seed)
  --profile NAME          comparable (flashrt long + env hints) | stress (repeat fill)
  --stream                Use stream=true payloads (default)
  --no-stream             Use stream=false (legacy non-streaming)
  --serve-log PATH        flashcli serve.log (engine TTFT/decode → metrics + report)
  --write-report          Write ${WORKDIR}/REPORT.md after bench (needs serve.log)
  -h, --help

Env: HOST, QWEN3_PORT, QWEN36_PORT, CKPT_QWEN3, CKPT_QWEN36, SHORT_PROMPT,
     QWEN3_MAX_Q_SEQ, QWEN36_MAX_SEQ, LONG_PROMPT_STYLE, BENCH_PROFILE,
     BENCH_ROUNDS, BENCH_SKIP_FIRST, BENCH_STREAM,
     SERVE_LOG_PATH (or QWEN36_SERVE_LOG) — flashcli serve log for engine TTFT/decode

Stream: qwen3 has true token SSE (client_ttft_ms = first content chunk).
qwen36: engine TTFT/decode from FlashRT serve.log (stream | lines) or SSE usage;
client_ttft_ms is HTTP first chunk (diagnostic only, not used for decode tok/s).
EOF
}

log() { printf '[bench-qwen] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Find a regular file receiving flashcli serve stderr/stdout (tee target).
discover_serve_log_path() {
  local pid path fd cand
  if [[ -n "${SERVE_LOG_PATH:-}" && -f "${SERVE_LOG_PATH}" ]]; then
    printf '%s' "${SERVE_LOG_PATH}"
    return 0
  fi
  for cand in \
    "${QWEN36_SERVE_LOG:-}" \
    "${FLASHCLI_SERVE_LOG:-}" \
    "${HOME}/.flashcli/serve.log" \
    /tmp/qwen36-serve.log \
    /tmp/flashcli-serve.log; do
    [[ -n "${cand}" && -f "${cand}" ]] || continue
    printf '%s' "${cand}"
    return 0
  done
  if command -v pgrep >/dev/null 2>&1; then
    for pid in $(pgrep -f 'flashcli.*serve' 2>/dev/null || true); do
      for fd in 1 2; do
        path="$(readlink -f "/proc/${pid}/fd/${fd}" 2>/dev/null || true)"
        [[ -n "${path}" && -f "${path}" && "${path}" != /dev/* ]] || continue
        printf '%s' "${path}"
        return 0
      done
    done
  fi
  return 1
}

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
    --skip-payload-build) SKIP_PAYLOAD_BUILD=1; shift ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --skip-first) SKIP_FIRST="$2"; shift 2 ;;
    --long-prompt-style) LONG_PROMPT_STYLE="$2"; shift 2 ;;
    --profile)
      BENCH_PROFILE="$2"
      case "${BENCH_PROFILE}" in
        comparable)
          LONG_PROMPT_STYLE=flashrt
          SHORT_PROMPT="${SHORT_PROMPT:-Explain quantum entanglement in one short paragraph.}"
          ;;
        stress)
          LONG_PROMPT_STYLE=repeat
          ;;
        *) die "Unknown --profile ${BENCH_PROFILE} (use comparable or stress)" ;;
      esac
      shift 2
      ;;
    --stream) BENCH_STREAM=1; shift ;;
    --no-stream) BENCH_STREAM=0; shift ;;
    --serve-log) SERVE_LOG_PATH="$2"; shift 2 ;;
    --write-report) WRITE_REPORT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

case "${BENCH_STREAM}" in
  0|false|no|off) BENCH_STREAM=0 ;;
  *) BENCH_STREAM=1 ;;
esac

if [[ "${SKIP_QWEN3}" -eq 1 && "${SKIP_QWEN36}" -eq 1 ]]; then
  die "Cannot use both --qwen3-only and --qwen36-only"
fi

if ! [[ "${ROUNDS}" =~ ^[0-9]+$ ]] || [[ "${ROUNDS}" -lt 1 ]]; then
  die "--rounds must be a positive integer (got ${ROUNDS})"
fi
if [[ -z "${SKIP_FIRST}" ]]; then
  if [[ "${ROUNDS}" -gt 1 ]]; then
    SKIP_FIRST=1
  else
    SKIP_FIRST=0
  fi
fi
if ! [[ "${SKIP_FIRST}" =~ ^[0-9]+$ ]]; then
  die "--skip-first must be a non-negative integer (got ${SKIP_FIRST})"
fi
if [[ "${SKIP_FIRST}" -ge "${ROUNDS}" ]]; then
  die "--skip-first (${SKIP_FIRST}) must be < --rounds (${ROUNDS})"
fi
_SCORED_ROUNDS=$((ROUNDS - SKIP_FIRST))

mkdir -p "${WORKDIR}"
if [[ -z "${SERVE_LOG_PATH}" && -f "${WORKDIR}/serve.log" ]]; then
  SERVE_LOG_PATH="${WORKDIR}/serve.log"
fi
if [[ -z "${SERVE_LOG_PATH}" ]]; then
  _auto_serve_log="$(discover_serve_log_path 2>/dev/null || true)"
  if [[ -n "${_auto_serve_log}" ]]; then
    SERVE_LOG_PATH="${_auto_serve_log}"
    log "auto-detected SERVE_LOG_PATH=${SERVE_LOG_PATH}"
  fi
fi
if [[ "${WRITE_REPORT}" -eq 1 && -z "${SERVE_LOG_PATH}" ]]; then
  die "--write-report requires serve.log (tee serve stderr, --serve-log, or auto-detect failed)"
fi

# After CLI flags: cap qwen3 long prompt to fit assumed serve --max-q-seq.
_qwen3_cap_max_q_seq=""
if [[ -z "${QWEN3_MAX_Q_SEQ+x}" ]]; then
  _qwen3_cap_max_q_seq=1024
else
  case "${QWEN3_MAX_Q_SEQ}" in
    0|off|none|false|no|disable) _qwen3_cap_max_q_seq="" ;;
    *) _qwen3_cap_max_q_seq="${QWEN3_MAX_Q_SEQ}" ;;
  esac
fi
if [[ "${SKIP_QWEN3}" -eq 0 && "${SKIP_QWEN3_LONG}" -eq 0 && -n "${_qwen3_cap_max_q_seq}" ]]; then
  _qwen3_max_prompt=$((_qwen3_cap_max_q_seq - LONG_MAX_TOKENS))
  if [[ "${_qwen3_max_prompt}" -lt 1 ]]; then
    die "QWEN3_MAX_Q_SEQ=${_qwen3_cap_max_q_seq} too small for long_max_tokens=${LONG_MAX_TOKENS}"
  fi
  if [[ "${QWEN3_LONG_PROMPT_TOKENS}" -gt "${_qwen3_max_prompt}" ]]; then
    log "qwen3 long: capping ${QWEN3_LONG_PROMPT_TOKENS} → ${_qwen3_max_prompt} tokens (assume serve --max-q-seq=${_qwen3_cap_max_q_seq}; QWEN3_MAX_Q_SEQ=0 to disable)"
    QWEN3_LONG_PROMPT_TOKENS="${_qwen3_max_prompt}"
  fi
fi

command -v curl >/dev/null 2>&1 || die "curl not found"
command -v jq >/dev/null 2>&1 || die "jq not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"
[[ -f "${MAKE_PAYLOAD}" ]] || die "Missing ${MAKE_PAYLOAD}"
[[ -f "${STREAM_ONCE}" ]] || die "Missing ${STREAM_ONCE}"

mkdir -p "${WORKDIR}"

health() {
  local port="$1"
  curl -sf "http://${HOST}:${port}/health" >/dev/null 2>&1
}

make_short_payload() {
  local model="$1" out="$2"
  local stream_json=false
  [[ "${BENCH_STREAM}" -eq 1 ]] && stream_json=true
  jq -n \
    --arg model "${model}" \
    --arg content "${SHORT_PROMPT}" \
    --argjson max_tokens "${SHORT_MAX_TOKENS}" \
    --argjson stream "${stream_json}" \
    '{
      model: $model,
      messages: [{role: "user", content: $content}],
      max_tokens: $max_tokens,
      temperature: 0,
      top_p: 1,
      stream: $stream
    }
    + (if $stream then {stream_options: {include_usage: true}} else {} end)' >"${out}"
}

make_long_payload() {
  local ckpt="$1" model="$2" target_tokens="$3" out="$4"
  local max_seq="${5:-}"
  local -a extra=(--long-prompt-style "${LONG_PROMPT_STYLE}")
  if [[ "${BENCH_STREAM}" -eq 1 ]]; then
    extra+=(--stream)
  else
    extra+=(--no-stream)
  fi
  if [[ -n "${max_seq}" ]]; then
    extra+=(--max-seq "${max_seq}")
    extra+=(--seq-slack "${QWEN36_SEQ_SLACK:-32}")
    if [[ "${target_tokens}" -gt 8192 ]]; then
      log "  building long payload (chat-template fit, typically 2–8 min for 256K) …"
    fi
  fi
  python3 "${MAKE_PAYLOAD}" \
    --checkpoint "${ckpt}" \
    --model "${model}" \
    --target-prompt-tokens "${target_tokens}" \
    --max-tokens "${LONG_MAX_TOKENS}" \
    --output "${out}" \
    "${extra[@]}"
}

print_qwen36_hints() {
  [[ "${SKIP_QWEN36}" -eq 0 ]] || return 0
  # FlashRT serve tuning only; vLLM/PyTorch baseline ignores these env vars.
  case "${BENCH_ARM:-flashrt}" in
    vllm|hf|pytorch*) return 0 ;;
  esac
  log "qwen36 hints (FlashRT serve only — for decode comparable to FlashRT docs on 5090/PRO 5000):"
  log "  export FLASHRT_QWEN36_LONG_KV_CACHE=fp8"
  log "  export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512"
  log "  long prompt: --profile comparable  OR  --long-prompt-style flashrt"
  log "  256K: QWEN36_MAX_SEQ=<serve --max-seq>  (repeat fill lowers MTP vs flashrt seed)"
  if [[ -n "${SERVE_LOG_PATH:-}" ]]; then
    log "  optional engine metrics: SERVE_LOG_PATH=${SERVE_LOG_PATH}"
  fi
}

# One HTTP request; append one JSON line to metrics jsonl. Prints brief round log.
serve_log_offset() {
  local log_path="$1"
  if [[ -f "${log_path}" ]]; then
    wc -c <"${log_path}" | tr -d ' '
  else
    echo 0
  fi
}

merge_serve_log_metrics() {
  local resp="$1" log_path="$2" offset="$3"
  local backend="${4:-auto}"
  [[ -f "${log_path}" ]] || return 0
  local metrics
  metrics="$(python3 "${SERVE_METRICS_PY}" --log "${log_path}" --offset "${offset}" --backend "${backend}" 2>/dev/null || true)"
  [[ -n "${metrics}" && "${metrics}" != "null" ]] || return 0
  jq --argjson m "${metrics}" '
    .usage = ((.usage // {}) + ($m | del(.metrics_source)))
    | .bench = ((.bench // {}) + {
        server_ttft_ms: ($m.ttft_ms // $m.first_delta_ms),
        ttft_ms: ($m.ttft_ms // $m.first_delta_ms),
        ttft_source: "engine",
        metrics_source: $m.metrics_source
      })
  ' "${resp}" >"${resp}.metrics.tmp" && mv "${resp}.metrics.tmp" "${resp}"
}

rehydrate_workdir_from_serve_log() {
  local wd="$1" log="$2" backend="${3:-auto}"
  [[ -f "${log}" ]] || return 0
  python3 "${SERVE_METRICS_PY}" --rehydrate-workdir "${wd}" --log "${log}" --backend "${backend}" \
    >/dev/null 2>&1 || true
}

write_bench_manifest() {
  jq -n \
    --argjson rounds "${ROUNDS}" \
    --argjson skip_first "${SKIP_FIRST}" \
    --arg profile "${BENCH_PROFILE:-}" \
    --arg serve_log "${SERVE_LOG_PATH:-}" \
    --arg bench_arm "${BENCH_ARM:-flashrt}" \
    --arg host "${HOST}" \
    --argjson qwen36_port "${QWEN36_PORT}" \
    '{
      rounds: $rounds,
      skip_first: $skip_first,
      profile: (if $profile != "" then $profile else null end),
      serve_log_path: (if $serve_log != "" then $serve_log else null end),
      bench_arm: $bench_arm,
      host: $host,
      qwen36_port: $qwen36_port
    }' >"${WORKDIR}/manifest.json"
}

write_curl_report() {
  local report_py="${SCRIPT_DIR}/bench_qwen36_report.py"
  [[ -f "${report_py}" ]] || return 0
  rehydrate_workdir_from_serve_log "${WORKDIR}" "${SERVE_LOG_PATH:-${WORKDIR}/serve.log}" "${SERVE_LOG_BACKEND:-auto}"
  local backend_label="FlashRT HTTP bench"
  case "${BENCH_ARM:-flashrt}" in
    vllm) backend_label="vLLM HTTP bench" ;;
    hf|pytorch*) backend_label="PyTorch-HF HTTP bench" ;;
  esac
  log "Writing ${WORKDIR}/REPORT.md (engine TTFT from serve.log when available)"
  python3 "${report_py}" --out "${WORKDIR}" --backend "${backend_label}" "${WORKDIR}" \
    >"${WORKDIR}/report.stdout.log" 2>&1 \
    || log "WARN: report generation failed (see ${WORKDIR}/report.stdout.log)"
}

run_curl_once() {
  local label="$1" port="$2" payload="$3" resp="$4" round="$5" jsonl="$6"
  local wall_ms tag="" use_stream=false log_offset=0
  if [[ "${round}" -le "${SKIP_FIRST}" ]]; then
    tag=" (warmup, excluded)"
  fi
  if [[ "$(jq -r '.stream // false' "${payload}")" == "true" ]]; then
    use_stream=true
  fi
  if [[ "${use_stream}" == "true" && -n "${SERVE_LOG_PATH:-}" && "${port}" == "${QWEN36_PORT}" ]]; then
    log_offset="$(serve_log_offset "${SERVE_LOG_PATH}")"
  fi
  if [[ "${use_stream}" == "true" ]]; then
    if ! python3 "${STREAM_ONCE}" \
      --url "http://${HOST}:${port}/v1/chat/completions" \
      --payload "${payload}" \
      -o "${resp}" 2>"${resp}.stderr"; then
      if [[ -s "${resp}.stderr" ]]; then
        cat "${resp}.stderr" >&2
      fi
      if [[ -s "${resp}" ]]; then
        jq -r '.' "${resp}" 2>/dev/null || cat "${resp}" >&2
      fi
      die "${label} round ${round}/${ROUNDS}: stream request failed"
    fi
  else
    local t0 t1
    t0="$(python3 -c 'import time; print(int(time.time()*1000))')"
    if ! curl -sf "http://${HOST}:${port}/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -d @"${payload}" \
      -o "${resp}"; then
      if [[ -s "${resp}" ]]; then
        log "${label} round ${round}/${ROUNDS}: server response:"
        jq -r '.' "${resp}" 2>/dev/null || cat "${resp}" >&2
      fi
      die "${label} round ${round}/${ROUNDS}: curl failed (is serve running on :${port}?)"
    fi
    t1="$(python3 -c 'import time; print(int(time.time()*1000))')"
    wall_ms=$((t1 - t0))
  fi
  if [[ ! -s "${resp}" ]]; then
    die "${label} round ${round}/${ROUNDS}: empty response"
  fi
  if jq -e '.error' "${resp}" >/dev/null 2>&1; then
    jq -r '.error | tostring' "${resp}" >&2
    die "${label} round ${round}/${ROUNDS}: API error"
  fi
  if [[ "${use_stream}" == "true" ]]; then
    wall_ms="$(jq -r '.bench.wall_ms // 0' "${resp}")"
    if [[ -n "${SERVE_LOG_PATH:-}" && "${port}" == "${QWEN36_PORT}" ]]; then
      merge_serve_log_metrics "${resp}" "${SERVE_LOG_PATH}" "${log_offset}" "${SERVE_LOG_BACKEND:-auto}"
    fi
  fi
  if jq -e '.bench.stream == true' "${resp}" >/dev/null 2>&1; then
    local ct preview
    ct="$(jq -r '.usage.completion_tokens // 0' "${resp}" 2>/dev/null)"
    preview="$(jq -r '.choices[0].message.content // ""' "${resp}" 2>/dev/null | head -c 80)"
    if [[ "${ct}" == "0" || -z "${preview}" ]]; then
      log "  WARN round ${round}: 0 completion tokens or empty text — check ${resp} and serve.log"
      jq -r '.error // empty' "${resp}" 2>/dev/null | head -5 >&2 || true
    fi
  fi
  jq -cn \
    --argjson round "${round}" \
    --argjson wall_ms "${wall_ms}" \
    --argjson usage "$(jq '.usage // {}' "${resp}")" \
    --argjson bench "$(jq '.bench // {}' "${resp}")" \
    '{round: $round, wall_ms: $wall_ms, usage: $usage, bench: $bench}' >>"${jsonl}"
  local tps client_ttft engine_ttft prefill_ms route msrc
  tps="$(jq -r '.usage.decode_tok_per_s // .usage.tok_per_s // "n/a"' "${resp}" 2>/dev/null)"
  client_ttft="$(jq -r '.bench.client_ttft_ms // "n/a"' "${resp}" 2>/dev/null)"
  engine_ttft="$(jq -r '.bench.server_ttft_ms // .usage.ttft_ms // empty' "${resp}" 2>/dev/null)"
  prefill_ms="$(jq -r '.usage.prefill_ms // empty' "${resp}" 2>/dev/null)"
  route="$(jq -r '.usage.route // empty' "${resp}" 2>/dev/null)"
  msrc="$(jq -r '.bench.metrics_source // empty' "${resp}" 2>/dev/null)"
  if [[ -n "${msrc}" && -n "${engine_ttft}" ]]; then
    log "  round ${round}/${ROUNDS}${tag}: wall=${wall_ms}ms prefill=${prefill_ms:-n/a} engine_ttft=${engine_ttft} client_ttft=${client_ttft} decode=${tps} tok/s${route:+ route=${route}} src=${msrc}"
  elif [[ -n "${engine_ttft}" ]]; then
    log "  round ${round}/${ROUNDS}${tag}: wall=${wall_ms}ms prefill=${prefill_ms:-n/a} engine_ttft=${engine_ttft} client_ttft=${client_ttft} decode=${tps} tok/s${route:+ route=${route}}"
  else
    log "  round ${round}/${ROUNDS}${tag}: wall=${wall_ms}ms client_ttft=${client_ttft} decode=${tps} tok/s${route:+ route=${route}}"
  fi
  if [[ "${port}" == "${QWEN36_PORT}" && "${tps}" == "n/a" ]]; then
    case "${BENCH_ARM:-flashrt}" in
      vllm)
        log "  WARN: no vLLM decode tok/s — need completion_tokens in final SSE usage (stream_options.include_usage=true)"
        ;;
      *)
        log "  WARN: no engine decode tok/s — tee serve stderr to a log and set SERVE_LOG_PATH (FlashRT stream | lines)"
        ;;
    esac
  fi
}

summarize_rounds() {
  local label="$1" jsonl="$2" last_resp="$3"
  python3 - "${label}" "${jsonl}" "${SKIP_FIRST}" "${ROUNDS}" "${_SCORED_ROUNDS}" <<'PY'
import json
import sys

label, path, skip_s, rounds_s, scored_s = sys.argv[1:6]
skip = int(skip_s)
rounds = int(rounds_s)
scored_n = int(scored_s)

rows = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))
if len(rows) != rounds:
    raise SystemExit(f"expected {rounds} metrics lines, got {len(rows)}")

samples = rows[skip:]
if not samples:
    raise SystemExit("no samples after skip")

def mean(key, nested="usage"):
    vals = []
    for r in samples:
        obj = r[nested] if nested else r
        v = obj.get(key)
        if v is not None:
            vals.append(float(v))
    return sum(vals) / len(vals) if vals else None

def mean_nested(key, nested="bench"):
    vals = []
    for r in samples:
        obj = r.get(nested) or {}
        v = obj.get(key)
        if v is not None:
            vals.append(float(v))
    return sum(vals) / len(vals) if vals else None

def mean_ttft_ms(engine=True):
    """Engine TTFT from serve.log merge or usage; client only if engine missing."""
    vals = []
    for r in samples:
        b = r.get("bench") or {}
        u = r.get("usage") or {}
        v = None
        if engine:
            v = b.get("server_ttft_ms")
            if v is None and (b.get("metrics_source") or u.get("metrics_source")):
                v = u.get("ttft_ms") or u.get("first_delta_ms")
            if v is None:
                v = u.get("ttft_ms") or u.get("first_delta_ms")
        if v is None and not engine:
            v = b.get("client_ttft_ms")
        if v is not None:
            vals.append(float(v))
    return sum(vals) / len(vals) if vals else None

def fmt(key, nested="usage", digits=1):
    m = mean(key, nested)
    if m is None:
        return None
    if key in ("prompt_tokens", "completion_tokens"):
        return f"{key}={int(round(m))}"
    if nested == "":
        return f"{key}={m:.0f}"
    return f"{key}={m:.{digits}f}"

parts = []
client_ttft_m = mean_nested("client_ttft_ms", "bench")
if client_ttft_m is not None:
    parts.append(f"client_ttft_ms={client_ttft_m:.1f}")
engine_ttft_m = mean_ttft_ms(engine=True)
if engine_ttft_m is not None:
    parts.append(f"engine_ttft_ms={engine_ttft_m:.1f}")
prefill_m = mean("prefill_ms", "usage")
if prefill_m is not None:
    parts.append(f"prefill_ms={prefill_m:.1f}")
for k in (
    "prompt_tokens",
    "completion_tokens",
    "prefill_ms",
    "decode_ms",
    "wall_s",
    "tok_per_s",
    "decode_tok_per_s",
    "e2e_tok_per_s",
):
    s = fmt(k)
    if s:
        parts.append(s)
wall = fmt("wall_ms", nested="", digits=0)
if wall:
    parts.insert(0, wall.replace("wall_ms=", "curl_wall_ms_mean="))
routes = [
    r.get("usage", {}).get("route")
    for r in samples
    if r.get("usage", {}).get("route") is not None
]
if routes:
    parts.append(f"route={routes[-1]}")

print(f"━━ {label} (mean of {scored_n} rounds, skipped first {skip}) ━━", file=sys.stderr)
print("  usage (mean): " + " ".join(parts), file=sys.stderr)
PY
  local preview
  preview="$(jq -r '.choices[0].message.content // ""' "${last_resp}" 2>/dev/null | head -c 120)"
  if [[ -n "${preview}" ]]; then
    log "  text[0:120] (last round): ${preview}…"
  fi
}

run_bench_case() {
  local label="$1" port="$2" payload="$3" stem="$4"
  local jsonl="${WORKDIR}/${stem}.metrics.jsonl"
  local r resp
  : >"${jsonl}"
  for ((r = 1; r <= ROUNDS; r++)); do
    resp="${WORKDIR}/${stem}.r${r}.out.json"
    run_curl_once "${label}" "${port}" "${payload}" "${resp}" "${r}" "${jsonl}"
  done
  summarize_rounds "${label}" "${jsonl}" "${WORKDIR}/${stem}.r${ROUNDS}.out.json"
}

log "workdir=${WORKDIR}  rounds=${ROUNDS} skip_first=${SKIP_FIRST} scored=${_SCORED_ROUNDS} stream=${BENCH_STREAM} long_prompt_style=${LONG_PROMPT_STYLE} profile=${BENCH_PROFILE:-none}"
if [[ "${BENCH_STREAM}" -eq 1 ]]; then
  case "${BENCH_ARM:-flashrt}" in
    vllm)
      log "stream=true: vLLM decode/TTFT from HTTP stream phase (first content chunk → end; src=vllm_http_stream)"
      ;;
    *)
      if [[ -n "${SERVE_LOG_PATH:-}" ]]; then
        log "stream=true: engine TTFT/decode from serve.log; client_ttft=HTTP first chunk (diagnostic)"
      else
        log "stream=true: set SERVE_LOG_PATH=<serve.log> for engine decode tok/s (FlashRT stream | lines)"
      fi
      ;;
  esac
fi
print_qwen36_hints
if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
  log "qwen3 → http://${HOST}:${QWEN3_PORT}  ckpt=${CKPT_QWEN3}"
fi
if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
  case "${BENCH_ARM:-flashrt}" in
    vllm)
      log "HTTP bench → http://${HOST}:${QWEN36_PORT}  backend=vLLM  weights=${CKPT_QWEN36}"
      ;;
    hf|pytorch*)
      log "HTTP bench → http://${HOST}:${QWEN36_PORT}  backend=PyTorch-HF  weights=${CKPT_QWEN36}"
      ;;
    *)
      log "HTTP bench → http://${HOST}:${QWEN36_PORT}  backend=FlashRT  weights=${CKPT_QWEN36}"
      ;;
  esac
fi

if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
  health "${QWEN3_PORT}" || die "qwen3 not healthy at :${QWEN3_PORT} (/health)"
fi
if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
  health "${QWEN36_PORT}" || die "qwen36 not healthy at :${QWEN36_PORT} (/health)"
fi

if [[ "${SKIP_SHORT}" -eq 0 ]]; then
  if [[ "${SKIP_QWEN3}" -eq 0 ]]; then
    if [[ "${SKIP_PAYLOAD_BUILD}" -eq 0 ]]; then
      make_short_payload "${QWEN3_MODEL}" "${WORKDIR}/qwen3_short.json"
    else
      [[ -f "${WORKDIR}/qwen3_short.json" ]] || die "missing ${WORKDIR}/qwen3_short.json (--skip-payload-build)"
    fi
    run_bench_case "qwen3 short ctx" "${QWEN3_PORT}" \
      "${WORKDIR}/qwen3_short.json" "qwen3_short"
  fi
  if [[ "${SKIP_QWEN36}" -eq 0 ]]; then
    if [[ "${SKIP_PAYLOAD_BUILD}" -eq 0 ]]; then
      make_short_payload "${QWEN36_MODEL}" "${WORKDIR}/qwen36_short.json"
    else
      [[ -f "${WORKDIR}/qwen36_short.json" ]] || die "missing ${WORKDIR}/qwen36_short.json (--skip-payload-build)"
    fi
    run_bench_case "qwen36 short ctx" "${QWEN36_PORT}" \
      "${WORKDIR}/qwen36_short.json" "qwen36_short"
  fi
fi

if [[ "${SKIP_QWEN3}" -eq 0 && "${SKIP_QWEN3_LONG}" -eq 0 ]]; then
  qwen3_long_tokens="${QWEN3_LONG_PROMPT_TOKENS}"
  log "qwen3 long: target prompt_tokens=${qwen3_long_tokens} (serve --max-q-seq >= this; prompt+decode <= --max-seq)"
  make_long_payload "${CKPT_QWEN3}" "${QWEN3_MODEL}" \
    "${qwen3_long_tokens}" "${WORKDIR}/qwen3_long.json"
  run_bench_case "qwen3 long ctx (prompt≈${qwen3_long_tokens})" "${QWEN3_PORT}" \
    "${WORKDIR}/qwen3_long.json" "qwen3_long"
fi

if [[ "${SKIP_QWEN36}" -eq 0 && "${SKIP_QWEN36_LONG}" -eq 0 ]]; then
  _qwen36_max_seq="${QWEN36_MAX_SEQ:-}"
  if [[ -n "${_qwen36_max_seq}" ]]; then
    log "qwen36 long: target user_tokens=${QWEN36_LONG_PROMPT_TOKENS}, fit to serve --max-seq=${_qwen36_max_seq} (+ chat template)"
  else
    log "qwen36 long: target user_tokens=${QWEN36_LONG_PROMPT_TOKENS} (set QWEN36_MAX_SEQ=<serve --max-seq> to auto-fit template overhead)"
  fi
  if [[ "${SKIP_PAYLOAD_BUILD}" -eq 0 ]]; then
    make_long_payload "${CKPT_QWEN36}" "${QWEN36_MODEL}" \
      "${QWEN36_LONG_PROMPT_TOKENS}" "${WORKDIR}/qwen36_long.json" "${_qwen36_max_seq}"
  else
    [[ -f "${WORKDIR}/qwen36_long.json" ]] || die "missing ${WORKDIR}/qwen36_long.json (--skip-payload-build)"
  fi
  run_bench_case "qwen36 long ctx (user≈${QWEN36_LONG_PROMPT_TOKENS})" "${QWEN36_PORT}" \
    "${WORKDIR}/qwen36_long.json" "qwen36_long"
fi

write_bench_manifest
if [[ -n "${SERVE_LOG_PATH:-}" && -f "${SERVE_LOG_PATH}" ]]; then
  if [[ "${SERVE_LOG_PATH}" != "${WORKDIR}/serve.log" ]]; then
    cp -f "${SERVE_LOG_PATH}" "${WORKDIR}/serve.log" 2>/dev/null \
      || ln -sf "$(realpath "${SERVE_LOG_PATH}" 2>/dev/null || echo "${SERVE_LOG_PATH}")" "${WORKDIR}/serve.log" 2>/dev/null \
      || true
  fi
  rehydrate_workdir_from_serve_log "${WORKDIR}" "${SERVE_LOG_PATH}" "${SERVE_LOG_BACKEND:-auto}"
fi
if [[ "${WRITE_REPORT}" -eq 1 ]]; then
  write_curl_report
fi
log "Done. Payloads and responses in ${WORKDIR}"
if [[ -f "${WORKDIR}/REPORT.md" ]]; then
  log "Report: ${WORKDIR}/REPORT.md"
fi
