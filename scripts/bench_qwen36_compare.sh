#!/usr/bin/env bash
# Qwen36 bench: flashcli+FlashRT vs PyTorch HF — same checkpoint, same payloads, serial steps.
#
#   bash scripts/bench_qwen36_compare.sh --quick
#   bash scripts/bench_qwen36_compare.sh --quick --pytorch-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BENCH_CURL="${SCRIPT_DIR}/bench_qwen_curl.sh"
MAKE_PAYLOAD="${SCRIPT_DIR}/bench_qwen_make_payload.py"
HF_SERVER="${SCRIPT_DIR}/bench_qwen36_hf_server.py"
REPORT_PY="${SCRIPT_DIR}/bench_qwen36_report.py"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
K="${K:-6}"
MAX_SEQ="${MAX_SEQ:-262208}"
WARMUP_PRESET="${WARMUP_PRESET:-agent}"
ROUNDS="${ROUNDS:-12}"
SKIP_FIRST="${SKIP_FIRST:-2}"
BENCH_PROFILE="${BENCH_PROFILE:-comparable}"
LONG_TOKENS="${LONG_TOKENS:-262144}"
HF_ATTN="${HF_ATTN:-sdpa}"
HF_DTYPE="${HF_DTYPE:-auto}"
MODEL_NAME="${MODEL_NAME:-qwen3.6-27b-nvfp4}"
SHORT_PROMPT="${SHORT_PROMPT:-Explain quantum entanglement in one short paragraph.}"
SHORT_MAX_TOKENS="${SHORT_MAX_TOKENS:-64}"
LONG_MAX_TOKENS="${LONG_MAX_TOKENS:-64}"
SHORT_ONLY=0
QUICK=0
QUICK_MAX_SEQ="${QUICK_MAX_SEQ:-32768}"
MAX_SEQ_EXPLICIT=0
RUN_FLASHCLI=1
RUN_PYTORCH=1
REPORT_ONLY=0
KEEP_SERVER=0
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-1800}"
GPU_SETTLE_SEC="${GPU_SETTLE_SEC:-8}"

BUNDLE="${BUNDLE:-${FLASHCLI_ROOT}/bundles/qwen_nvfp4}"
CHECKPOINT="${CHECKPOINT:-${CKPT_QWEN36:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/checkpoint}}"
MTP_CKPT="${MTP_CKPT:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8}"
OUT_DIR="${OUT_DIR:-}"
PAYLOAD_DIR=""
SERVE_PID_FILE=""

usage() {
  cat <<EOF
Usage: bash scripts/bench_qwen36_compare.sh [OPTIONS]

Serial flow per backend: start serve → wait /health → bench_qwen_curl → stop serve → next.

  --quick              short ctx, max-seq ${QUICK_MAX_SEQ}, warmup none, 3 rounds
  --flashcli-only / --pytorch-only / --report-only
  --checkpoint PATH  --max-seq N  --out-dir DIR  --help

See script header for defaults.
EOF
}

log() { printf '[qwen36-compare] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --flashcli-only) RUN_PYTORCH=0; shift ;;
    --pytorch-only|--hf-only) RUN_FLASHCLI=0; shift ;;
    --report-only) REPORT_ONLY=1; shift ;;
    --quick)
      QUICK=1
      SHORT_ONLY=1
      ROUNDS=3
      SKIP_FIRST=1
      WARMUP_PRESET=none
      [[ "${MAX_SEQ_EXPLICIT}" -eq 0 ]] && MAX_SEQ="${QUICK_MAX_SEQ}"
      shift
      ;;
    --short-only) SHORT_ONLY=1; shift ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --skip-first) SKIP_FIRST="$2"; shift 2 ;;
    --long-tokens|--qwen36-long-tokens) LONG_TOKENS="$2"; shift 2 ;;
    --profile) BENCH_PROFILE="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT="$2"; shift 2 ;;
    --mtp-checkpoint) MTP_CKPT="$2"; shift 2 ;;
    --hf-attn) HF_ATTN="$2"; shift 2 ;;
    --hf-dtype) HF_DTYPE="$2"; shift 2 ;;
    --model-name) MODEL_NAME="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --K) K="$2"; shift 2 ;;
    --max-seq) MAX_SEQ="$2"; MAX_SEQ_EXPLICIT=1; shift 2 ;;
    --warmup-preset) WARMUP_PRESET="$2"; shift 2 ;;
    --keep-server) KEEP_SERVER=1; shift ;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
    --gpu-settle-sec) GPU_SETTLE_SEC="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ "${RUN_FLASHCLI}" -eq 1 || "${RUN_PYTORCH}" -eq 1 ]] || die "Nothing to run"

if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="/tmp/qwen36-bench-$(date +%Y%m%d-%H%M%S)"
fi
OUT_DIR="$(cd "$(dirname "${OUT_DIR}")" && pwd)/$(basename "${OUT_DIR}")"
mkdir -p "${OUT_DIR}"
PAYLOAD_DIR="${OUT_DIR}/payloads"

if [[ "${REPORT_ONLY}" -eq 0 ]]; then
  command -v curl >/dev/null 2>&1 || die "curl not found"
  command -v jq >/dev/null 2>&1 || die "jq not found"
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  [[ -d "${CHECKPOINT}" ]] || die "Checkpoint not found: ${CHECKPOINT}"
fi

gpu_name() {
  nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "unknown"
}

free_port() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
  sleep 1
}

kill_serve_procs() {
  local p
  for p in $(pgrep -f "flashcli.*serve qwen36|bench_qwen36_hf_server.py|flashcli.cli serve qwen36" 2>/dev/null || true); do
    [[ "${p}" == "$$" ]] && continue
    kill -TERM "${p}" 2>/dev/null || true
  done
  sleep 1
}

stop_serve() {
  [[ "${KEEP_SERVER}" -eq 1 ]] && return 0
  if [[ -n "${SERVE_PID_FILE}" && -f "${SERVE_PID_FILE}" ]]; then
    local pid
    pid="$(tr -d '[:space:]' <"${SERVE_PID_FILE}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      log "Stopping serve pid=${pid}"
      kill -TERM "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
    fi
    rm -f "${SERVE_PID_FILE}"
    SERVE_PID_FILE=""
  fi
  kill_serve_procs
  free_port
  if (( GPU_SETTLE_SEC > 0 )); then
    log "GPU settle ${GPU_SETTLE_SEC}s …"
    sleep "${GPU_SETTLE_SEC}"
  fi
}

cleanup_on_exit() {
  local ec=$?
  stop_serve >/dev/null 2>&1 || true
  return "${ec}"
}

check_serve_log_fatal() {
  local serve_log="$1"
  [[ -f "${serve_log}" ]] || return 0
  if grep -q 'Invalid model bundle:' "${serve_log}"; then
    tail -n 20 "${serve_log}" >&2 || true
    die "Bundle not built (missing lib/ flash_rt/). See bundles/qwen_nvfp4/QUICKSTART.md"
  fi
  if grep -qE 'Failed to load checkpoint|does not recognize this architecture|Qwen3_5ForCausalLM|Cannot import Qwen3_5' "${serve_log}"; then
    tail -n 20 "${serve_log}" >&2 || true
    die "HF load failed — need transformers>=5 (Qwen3_5ForCausalLM) and compressed-tensors>=0.14; see serve.log"
  fi
}

wait_health() {
  local serve_log="$1"
  local start now elapsed=0 last_hint=0
  start="$(date +%s)"
  log "Step: wait http://${HOST}:${PORT}/health (log: ${serve_log})"
  while true; do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      now="$(date +%s)"
      log "  /health OK (${now - start}s)"
      echo $((now - start))
      return 0
    fi
    check_serve_log_fatal "${serve_log}"
    if [[ -n "${SERVE_PID_FILE}" && -f "${SERVE_PID_FILE}" ]]; then
      local pid
      pid="$(tr -d '[:space:]' <"${SERVE_PID_FILE}")"
      if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
        log "Serve process exited. Last lines of ${serve_log}:"
        tail -n 30 "${serve_log}" >&2 || true
        die "Server died before /health"
      fi
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if (( elapsed >= HEALTH_TIMEOUT )); then
      tail -n 40 "${serve_log}" >&2 || true
      die "Timed out waiting for /health"
    fi
    if (( elapsed - last_hint >= 60 )); then
      last_hint=${elapsed}
      log "  … waiting (${elapsed}s)"
      tail -n 3 "${serve_log}" 2>/dev/null | sed 's/^/    /' >&2 || true
    fi
    sleep 5
  done
}

start_serve() {
  local workdir="$1"
  shift
  local serve_log="${workdir}/serve.log"
  SERVE_PID_FILE="${workdir}/serve.pid"
  stop_serve
  : >"${serve_log}"
  log "Step: start serve → ${serve_log}"
  (
    cd "${FLASHCLI_ROOT}"
    "$@"
  ) >>"${serve_log}" 2>&1 &
  echo $! >"${SERVE_PID_FILE}"
  log "  pid=$(cat "${SERVE_PID_FILE}")"
}

long_prompt_style() {
  case "${BENCH_PROFILE}" in
    comparable|stress) echo "flashrt" ;;
    *) echo "${LONG_PROMPT_STYLE:-repeat}" ;;
  esac
}

prepare_shared_payloads() {
  mkdir -p "${PAYLOAD_DIR}"
  log "Step: build payloads (max_seq=${MAX_SEQ})"
  jq -n \
    --arg model "${MODEL_NAME}" \
    --arg content "${SHORT_PROMPT}" \
    --argjson max_tokens "${SHORT_MAX_TOKENS}" \
    '{model: $model, messages: [{role: "user", content: $content}], max_tokens: $max_tokens, temperature: 0, stream: true}' \
    >"${PAYLOAD_DIR}/qwen36_short.json"
  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    log "  qwen36_short.json only"
    return 0
  fi
  python3 "${MAKE_PAYLOAD}" \
    --checkpoint "${CHECKPOINT}" \
    --model "${MODEL_NAME}" \
    --target-prompt-tokens "${LONG_TOKENS}" \
    --max-tokens "${LONG_MAX_TOKENS}" \
    --output "${PAYLOAD_DIR}/qwen36_long.json" \
    --long-prompt-style "$(long_prompt_style)" \
    --stream --max-seq "${MAX_SEQ}" --seq-slack 32
}

write_manifest_header() {
  local workdir="$1" backend="$2" server_cmd="$3" started_at="$4" health_wait_s="$5"
  local extra_json="${6:-{}}"
  jq -n \
    --arg backend "${backend}" \
    --arg started_at "${started_at}" \
    --argjson health_wait_s "${health_wait_s}" \
    --arg gpu_name "$(gpu_name)" \
    --arg server_cmd "${server_cmd}" \
    --arg host "${HOST}" \
    --argjson port "${PORT}" \
    --argjson K "${K}" \
    --argjson max_seq "${MAX_SEQ}" \
    --arg warmup_preset "${WARMUP_PRESET}" \
    --argjson rounds "${ROUNDS}" \
    --argjson skip_first "${SKIP_FIRST}" \
    --arg profile "${BENCH_PROFILE}" \
    --argjson long_tokens "${LONG_TOKENS}" \
    --argjson short_only "${SHORT_ONLY}" \
    --arg checkpoint "${CHECKPOINT}" \
    --arg mtp_checkpoint "${MTP_CKPT}" \
    --arg payload_dir "${PAYLOAD_DIR}" \
    --arg bundle "${BUNDLE}" \
    --argjson extra "${extra_json}" \
    '{backend: $backend, started_at: $started_at, health_wait_s: $health_wait_s, gpu_name: $gpu_name,
      server_cmd: $server_cmd, host: $host, port: $port, K: $K, max_seq: $max_seq,
      warmup_preset: $warmup_preset, rounds: $rounds, skip_first: $skip_first, profile: $profile,
      long_tokens: $long_tokens, short_only: ($short_only != 0), checkpoint: $checkpoint,
      mtp_checkpoint: $mtp_checkpoint, payload_dir: $payload_dir, bundle: $bundle,
      shared_weights: true, shared_payloads: true} + $extra' >"${workdir}/manifest.json"
}

finish_manifest() {
  local workdir="$1" finished
  finished="$(date -Iseconds 2>/dev/null || date)"
  jq --arg finished "${finished}" '. + {finished_at: $finished}' \
    "${workdir}/manifest.json" >"${workdir}/manifest.json.tmp"
  mv "${workdir}/manifest.json.tmp" "${workdir}/manifest.json"
}

run_bench_cases() {
  local workdir="$1"
  cp "${PAYLOAD_DIR}/qwen36_short.json" "${workdir}/qwen36_short.json"
  [[ "${SHORT_ONLY}" -eq 0 ]] && cp "${PAYLOAD_DIR}/qwen36_long.json" "${workdir}/qwen36_long.json"

  local -a args=(--qwen36-only --rounds "${ROUNDS}" --skip-first "${SKIP_FIRST}"
    --workdir "${workdir}" --skip-payload-build)
  [[ -n "${BENCH_PROFILE}" ]] && args+=(--profile "${BENCH_PROFILE}")
  [[ "${SHORT_ONLY}" -eq 1 ]] && args+=(--skip-qwen36-long)

  log "Step: bench_qwen_curl.sh"
  export CKPT_QWEN36="${CHECKPOINT}" HOST QWEN36_PORT="${PORT}" QWEN36_MAX_SEQ="${MAX_SEQ}"
  bash "${BENCH_CURL}" "${args[@]}" 2>&1 | tee "${workdir}/bench.log"
}

run_flashcli_backend() {
  local workdir="${OUT_DIR}/flashcli"
  [[ -f "${BUNDLE}/flashcli-bundle.json" ]] || die "Bundle missing: ${BUNDLE}"
  [[ -f "${MTP_CKPT}/mtp.safetensors" ]] || die "MTP missing: ${MTP_CKPT}/mtp.safetensors"
  mkdir -p "${workdir}"

  local -a cmd
  local -a env_args=(FLASHRT_QWEN36_MTP_CKPT_DIR="${MTP_CKPT}" FLASHRT_QWEN36_LONG_KV_CACHE=fp8)
  if command -v flashcli >/dev/null 2>&1; then
    cmd=(flashcli serve qwen36-27b-nvfp4)
  else
    cmd=(python3 -m flashcli.cli serve qwen36-27b-nvfp4)
    env_args+=(PYTHONPATH="${FLASHCLI_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}")
  fi
  cmd+=(--bundle "${BUNDLE}" --checkpoint "${CHECKPOINT}" --host "${HOST}" --port "${PORT}"
    --K "${K}" --max-seq "${MAX_SEQ}" --warmup-preset "${WARMUP_PRESET}" --no-auto-install)

  local started server_cmd health_s
  started="$(date -Iseconds 2>/dev/null || date)"
  server_cmd="$(printf '%q ' env "${env_args[@]}" "${cmd[@]}")"

  log "━━ FlashRT backend ━━"
  start_serve "${workdir}" env "${env_args[@]}" "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log")"
  write_manifest_header "${workdir}" "flashcli+FlashRT" "${server_cmd}" "${started}" "${health_s}" \
    "$(jq -n '{stack: "FlashRT"}')"
  run_bench_cases "${workdir}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done FlashRT → ${workdir}"
}

run_pytorch_backend() {
  local workdir="${OUT_DIR}/pytorch_hf"
  mkdir -p "${workdir}"

  local -a cmd=(
    python3 "${HF_SERVER}"
    --checkpoint "${CHECKPOINT}"
    --model-name "${MODEL_NAME}"
    --host "${HOST}" --port "${PORT}"
    --max-seq "${MAX_SEQ}" --max-output-tokens 16384
    --attn "${HF_ATTN}" --dtype "${HF_DTYPE}"
  )
  local started server_cmd health_s
  started="$(date -Iseconds 2>/dev/null || date)"
  server_cmd="$(printf '%q ' "${cmd[@]}")"

  log "━━ PyTorch HF backend ━━"
  start_serve "${workdir}" "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log")"
  write_manifest_header "${workdir}" "PyTorch HF" "${server_cmd}" "${started}" "${health_s}" \
    "$(jq -n --arg a "${HF_ATTN}" --arg d "${HF_DTYPE}" '{stack: "transformers", hf_attn: $a, hf_dtype: $d}')"
  run_bench_cases "${workdir}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done PyTorch HF → ${workdir}"
}

write_report() {
  local -a args=(--out "${OUT_DIR}")
  [[ -d "${OUT_DIR}/flashcli" ]] && args+=(--flashcli "${OUT_DIR}/flashcli")
  [[ -d "${OUT_DIR}/pytorch_hf" ]] && args+=(--pytorch "${OUT_DIR}/pytorch_hf")
  log "Step: report"
  python3 "${REPORT_PY}" "${args[@]}" >"${OUT_DIR}/REPORT.stdout.log" 2>&1
  log "Report: ${OUT_DIR}/REPORT.md"
}

log "out=${OUT_DIR} ckpt=${CHECKPOINT} max_seq=${MAX_SEQ} flashcli=${RUN_FLASHCLI} hf=${RUN_PYTORCH} quick=${QUICK}"
[[ "${QUICK}" -eq 1 ]] && log "GPU: $(gpu_name)"

if [[ "${REPORT_ONLY}" -eq 1 ]]; then
  write_report
  exit 0
fi

trap cleanup_on_exit INT TERM EXIT

prepare_shared_payloads
[[ "${RUN_FLASHCLI}" -eq 1 ]] && run_flashcli_backend
[[ "${RUN_PYTORCH}" -eq 1 ]] && run_pytorch_backend
write_report
log "All done: ${OUT_DIR}"
