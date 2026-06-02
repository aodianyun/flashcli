#!/usr/bin/env bash
# One-click qwen36 bench: flashcli + FlashRT vs PyTorch HF on the SAME checkpoint & payloads.
#
# Fairness guarantees:
#   - One --checkpoint directory for both backends (default: NVFP4 from flashcli pull)
#   - Same --max-seq and --long-tokens
#   - HTTP payloads built once and reused (identical prompt text + max_tokens)
#
# Examples:
#   bash scripts/bench_qwen36_compare.sh --quick
#   bash scripts/bench_qwen36_compare.sh --checkpoint ~/.flashcli/models/qwen36-27b-nvfp4/checkpoint
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_BG="${SCRIPT_DIR}/run_bg.sh"
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
RUN_FLASHCLI=1
RUN_PYTORCH=1
REPORT_ONLY=0
KEEP_SERVER=0
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-1800}"
GPU_IDLE_MAX_MIB="${GPU_IDLE_MAX_MIB:-1024}"
GPU_IDLE_TIMEOUT="${GPU_IDLE_TIMEOUT:-180}"
GPU_SETTLE_SEC="${GPU_SETTLE_SEC:-8}"
JOB_PREFIX="${JOB_PREFIX:-qwen36-bench}"

BUNDLE="${BUNDLE:-${FLASHCLI_ROOT}/bundles/qwen_nvfp4}"
CHECKPOINT="${CHECKPOINT:-${CKPT_QWEN36:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/checkpoint}}"
MTP_CKPT="${MTP_CKPT:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8}"
OUT_DIR="${OUT_DIR:-}"
PAYLOAD_DIR=""

usage() {
  cat <<EOF
Usage: bash scripts/bench_qwen36_compare.sh [OPTIONS]

Compares the SAME model weights and the SAME HTTP payloads:

  A) flashcli serve + FlashRT  (NVFP4 + MTP speculative decode)
  B) PyTorch HF baseline         (transformers greedy decode, no FlashRT)

Modes:
  (default)             Both backends + unified REPORT.md
  --flashcli-only       FlashRT path only
  --pytorch-only        PyTorch HF only  (alias: --hf-only)
  --report-only         Rebuild report from --out-dir

Bench:
  --quick               Short ctx only; warmup-preset none; rounds=3 skip-first=1
  --short-only          Skip long-context case
  --rounds / --skip-first / --profile comparable|stress
  --long-tokens N       Long prompt user tokens (default: ${LONG_TOKENS})

Shared model (both backends MUST use this):
  --checkpoint PATH     Model directory (default: flashcli NVFP4 pull path)
  --mtp-checkpoint PATH MTP dir for FlashRT spec only (default: paired mtp_fp8/)
  --max-seq N           Context budget for BOTH (default: ${MAX_SEQ})
  --bundle PATH         flashcli qwen_nvfp4 bundle (FlashRT native .so)

FlashRT serve:
  --K N                 MTP K (default: ${K})
  --warmup-preset NAME  default: ${WARMUP_PRESET}

PyTorch HF baseline (same --checkpoint):
  --hf-attn NAME        sdpa | flash_attention_2 | eager (default: ${HF_ATTN})
  --hf-dtype NAME       auto|bf16|fp16 (default: ${HF_DTYPE})

Common:
  --out-dir DIR         Output root (default: /tmp/qwen36-bench-<ts>)
  --port N              HTTP port (default: ${PORT})
  --keep-server         Debug: leave server running (breaks GPU exclusivity)
  --gpu-idle-max-mib N  Max GPU mem (MiB) before next backend (default: ${GPU_IDLE_MAX_MIB})
  --gpu-idle-timeout SEC (default: ${GPU_IDLE_TIMEOUT})
  --gpu-settle-sec SEC  Sleep after GPU idle (default: ${GPU_SETTLE_SEC})

Strict GPU exclusivity (default):
  stop A → wait GPU idle → start B → bench → stop B → wait GPU idle → report

Pull weights once:
  flashcli pull qwen36-27b-nvfp4 --bundle bundles/qwen_nvfp4
  # PyTorch HF side loads the same NVFP4 checkpoint directory; install if needed:
  pip install compressed-tensors
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
      # agent warmup includes 256K shapes and blocks HTTP until done (30+ min).
      WARMUP_PRESET=none
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
    --max-seq) MAX_SEQ="$2"; shift 2 ;;
    --warmup-preset) WARMUP_PRESET="$2"; shift 2 ;;
    --keep-server) KEEP_SERVER=1; shift ;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
    --gpu-idle-max-mib) GPU_IDLE_MAX_MIB="$2"; shift 2 ;;
    --gpu-idle-timeout) GPU_IDLE_TIMEOUT="$2"; shift 2 ;;
    --gpu-settle-sec) GPU_SETTLE_SEC="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (use --help)" ;;
  esac
done

if [[ "${RUN_FLASHCLI}" -eq 0 && "${RUN_PYTORCH}" -eq 0 ]]; then
  die "Nothing to run"
fi

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
  [[ -f "${RUN_BG}" ]] || die "Missing ${RUN_BG}"
  [[ -f "${BENCH_CURL}" ]] || die "Missing ${BENCH_CURL}"
  [[ -f "${MAKE_PAYLOAD}" ]] || die "Missing ${MAKE_PAYLOAD}"
  [[ -f "${HF_SERVER}" ]] || die "Missing ${HF_SERVER}"
  [[ -f "${REPORT_PY}" ]] || die "Missing ${REPORT_PY}"
  [[ -d "${CHECKPOINT}" ]] || die "Checkpoint not found: ${CHECKPOINT}
Run: flashcli pull qwen36-27b-nvfp4 --bundle ${BUNDLE}"
fi

gpu_name() {
  nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "unknown"
}

gpu_memory_used_mib() {
  local v
  v="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]')"
  if [[ -z "${v}" || ! "${v}" =~ ^[0-9]+$ ]]; then
    echo "0"
  else
    echo "${v}"
  fi
}

gpu_compute_process_lines() {
  nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
    --format=csv,noheader 2>/dev/null | sed '/^$/d' | grep -v 'Not Found' || true
}

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tln "sport = :${port}" 2>/dev/null | grep -q LISTEN
    return $?
  fi
  curl -sf "http://${HOST}:${port}/health" >/dev/null 2>&1
}

free_port() {
  local port="$1"
  if ! port_in_use "${port}"; then
    return 0
  fi
  log "Releasing port ${port} …"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  elif command -v ss >/dev/null 2>&1; then
    local p
    while IFS= read -r p; do
      [[ -z "${p}" || "${p}" == "$$" ]] && continue
      kill -TERM "${p}" 2>/dev/null || true
    done < <(ss -tlnp "sport = :${port}" 2>/dev/null | grep -o 'pid=[0-9]*' | sed 's/pid=//' || true)
  fi
  sleep 1
}

kill_orphan_serve_procs() {
  local p pattern
  for pattern in \
    "flashcli serve qwen36" \
    "flashcli.cli serve qwen36" \
    "bench_qwen36_hf_server.py" \
    "qwen36_agent.server" \
    "uvicorn.*:${PORT}"; do
    while IFS= read -r p; do
      [[ -z "${p}" || "${p}" == "$$" ]] && continue
      log "Stopping orphan pid ${p} (${pattern})"
      kill -TERM "${p}" 2>/dev/null || true
    done < <(pgrep -f "${pattern}" 2>/dev/null || true)
  done
}

stop_job() {
  local name="$1"
  if [[ "${KEEP_SERVER}" -eq 1 ]]; then
    log "Keeping server job '${name}' (--keep-server)"
    return 0
  fi
  if bash "${RUN_BG}" --name "${name}" --stop >>"${OUT_DIR}/stop.log" 2>&1; then
    log "Stopped run_bg job '${name}'"
  else
    log "run_bg stop '${name}' (job may not exist)"
  fi
}

stop_all_bench_jobs() {
  stop_job "${JOB_PREFIX}-flashcli"
  stop_job "${JOB_PREFIX}-pytorch"
  kill_orphan_serve_procs
  free_port "${PORT}"
  sleep 1
  kill_orphan_serve_procs
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
}

wait_gpu_idle() {
  local label="$1"
  local timeout="${2:-${GPU_IDLE_TIMEOUT}}"
  local start now used lines
  start="$(date +%s)"
  log "Waiting for GPU idle before ${label} (mem<=${GPU_IDLE_MAX_MIB} MiB, timeout ${timeout}s) …"
  while true; do
    used="$(gpu_memory_used_mib)"
    lines="$(gpu_compute_process_lines)"
    if [[ -z "${lines}" && "${used}" -le "${GPU_IDLE_MAX_MIB}" ]]; then
      if (( GPU_SETTLE_SEC > 0 )); then
        log "GPU idle (used=${used} MiB); settling ${GPU_SETTLE_SEC}s …"
        sleep "${GPU_SETTLE_SEC}"
        used="$(gpu_memory_used_mib)"
        lines="$(gpu_compute_process_lines)"
        if [[ -z "${lines}" && "${used}" -le "${GPU_IDLE_MAX_MIB}" ]]; then
          log "GPU ready for ${label} (used=${used} MiB, no compute processes)"
          return 0
        fi
      else
        log "GPU ready for ${label} (used=${used} MiB, no compute processes)"
        return 0
      fi
    fi
    now="$(date +%s)"
    if (( now - start >= timeout )); then
      log "WARN: GPU not fully idle after ${timeout}s (used=${used} MiB)"
      if [[ -n "${lines}" ]]; then
        log "WARN: compute processes still present:"
        while IFS= read -r line; do
          [[ -n "${line}" ]] && log "  ${line}"
        done <<<"${lines}"
      fi
      die "Refusing to start ${label} while GPU is still occupied. Stop other jobs or raise --gpu-idle-timeout / --gpu-idle-max-mib."
    fi
    if (( (now - start) % 15 == 0 && now > start )); then
      log "  … still waiting (used=${used} MiB)"
      if [[ -n "${lines}" ]]; then
        log "  … compute: $(echo "${lines}" | tr '\n' '; ')"
      fi
    fi
    sleep 2
  done
}

ensure_gpu_exclusive() {
  local label="$1"
  log "━━ GPU exclusive gate: ${label} ━━"
  stop_all_bench_jobs
  wait_gpu_idle "${label}"
}

teardown_backend() {
  local job="$1" label="$2"
  log "━━ Teardown ${label}: stop serve + release GPU ━━"
  stop_job "${job}"
  if [[ "${KEEP_SERVER}" -eq 0 ]]; then
    stop_all_bench_jobs
    wait_gpu_idle "after ${label}"
  fi
}

cleanup_on_exit() {
  local ec=$?
  if [[ "${KEEP_SERVER}" -eq 1 ]]; then
    return 0
  fi
  stop_all_bench_jobs >/dev/null 2>&1 || true
  return "${ec}"
}

wait_health() {
  local port="$1" timeout="$2" serve_log="${3:-}"
  local start now elapsed last_hint=0
  start="$(date +%s)"
  log "Waiting for http://${HOST}:${port}/health (timeout ${timeout}s) …"
  log "  flashcli serve starts HTTP only after model load + warmup; see serve.log for progress."
  while true; do
    if curl -sf "http://${HOST}:${port}/health" >/dev/null 2>&1; then
      now="$(date +%s)"
      echo $((now - start))
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if (( now - start >= timeout )); then
      if [[ -n "${serve_log}" && -f "${serve_log}" ]]; then
        log "Last 40 lines of ${serve_log}:"
        tail -n 40 "${serve_log}" >&2 || true
      fi
      die "Timed out waiting for /health on port ${port}"
    fi
    if (( elapsed - last_hint >= 60 )); then
      last_hint="${elapsed}"
      log "  … still waiting for /health (${elapsed}s elapsed)"
      if [[ -n "${serve_log}" && -f "${serve_log}" ]]; then
        tail -n 3 "${serve_log}" 2>/dev/null | sed 's/^/[serve] /' >&2 || true
      fi
    fi
    sleep 5
  done
}

long_prompt_style() {
  case "${BENCH_PROFILE}" in
    comparable|stress) echo "flashrt" ;;
    *) echo "${LONG_PROMPT_STYLE:-repeat}" ;;
  esac
}

prepare_shared_payloads() {
  mkdir -p "${PAYLOAD_DIR}"
  log "Building shared payloads once (checkpoint=${CHECKPOINT}, max_seq=${MAX_SEQ}) …"

  local stream_json=true
  jq -n \
    --arg model "${MODEL_NAME}" \
    --arg content "${SHORT_PROMPT}" \
    --argjson max_tokens "${SHORT_MAX_TOKENS}" \
    --argjson stream "${stream_json}" \
    '{
      model: $model,
      messages: [{role: "user", content: $content}],
      max_tokens: $max_tokens,
      temperature: 0,
      stream: $stream
    }' >"${PAYLOAD_DIR}/qwen36_short.json"

  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    log "Shared payloads: qwen36_short.json only (--short-only)"
    return 0
  fi

  local -a extra=(--long-prompt-style "$(long_prompt_style)" --stream)
  extra+=(--max-seq "${MAX_SEQ}" --seq-slack 32)
  if [[ "${LONG_TOKENS}" -gt 8192 ]]; then
    log "  building long payload (chat-template fit, may take several minutes) …"
  fi
  python3 "${MAKE_PAYLOAD}" \
    --checkpoint "${CHECKPOINT}" \
    --model "${MODEL_NAME}" \
    --target-prompt-tokens "${LONG_TOKENS}" \
    --max-tokens "${LONG_MAX_TOKENS}" \
    --output "${PAYLOAD_DIR}/qwen36_long.json" \
    "${extra[@]}"
  log "Shared payloads ready under ${PAYLOAD_DIR}"
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
    '{
      backend: $backend,
      started_at: $started_at,
      health_wait_s: $health_wait_s,
      gpu_name: $gpu_name,
      server_cmd: $server_cmd,
      host: $host,
      port: $port,
      K: $K,
      max_seq: $max_seq,
      warmup_preset: $warmup_preset,
      rounds: $rounds,
      skip_first: $skip_first,
      profile: $profile,
      long_tokens: $long_tokens,
      short_only: ($short_only != 0),
      checkpoint: $checkpoint,
      mtp_checkpoint: $mtp_checkpoint,
      payload_dir: $payload_dir,
      bundle: $bundle,
      shared_weights: true,
      shared_payloads: true
    } + $extra' >"${workdir}/manifest.json"
}

finish_manifest() {
  local workdir="$1"
  local finished
  finished="$(date -Iseconds 2>/dev/null || date)"
  local tmp="${workdir}/manifest.json.tmp"
  jq --arg finished "${finished}" '. + {finished_at: $finished}' \
    "${workdir}/manifest.json" >"${tmp}"
  mv "${tmp}" "${workdir}/manifest.json"
}

run_bench_cases() {
  local workdir="$1"
  mkdir -p "${workdir}"
  cp "${PAYLOAD_DIR}/qwen36_short.json" "${workdir}/qwen36_short.json"
  if [[ "${SHORT_ONLY}" -eq 0 ]]; then
    cp "${PAYLOAD_DIR}/qwen36_long.json" "${workdir}/qwen36_long.json"
  fi

  local -a bench_args=(
    --qwen36-only
    --rounds "${ROUNDS}"
    --skip-first "${SKIP_FIRST}"
    --workdir "${workdir}"
    --skip-payload-build
  )
  if [[ -n "${BENCH_PROFILE}" ]]; then
    bench_args+=(--profile "${BENCH_PROFILE}")
  fi
  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    bench_args+=(--skip-qwen36-long)
  fi

  log "Running bench_qwen_curl.sh → ${workdir} (shared payloads, max_seq=${MAX_SEQ})"
  (
    export CKPT_QWEN36="${CHECKPOINT}" HOST QWEN36_PORT="${PORT}" QWEN36_MAX_SEQ="${MAX_SEQ}"
    bash "${BENCH_CURL}" "${bench_args[@]}"
  ) 2>&1 | tee "${workdir}/bench.log"
}

run_flashcli_backend() {
  local workdir="${OUT_DIR}/flashcli"
  local job="${JOB_PREFIX}-flashcli"
  local server_cmd started health_s

  [[ -f "${BUNDLE}/flashcli-bundle.json" ]] || die "Bundle missing: ${BUNDLE}"
  [[ -f "${MTP_CKPT}/mtp.safetensors" ]] || die "MTP not found: ${MTP_CKPT}/mtp.safetensors"

  ensure_gpu_exclusive "flashcli+FlashRT"
  mkdir -p "${workdir}"

  local -a serve_cmd
  local -a serve_env=(
    FLASHRT_QWEN36_MTP_CKPT_DIR="${MTP_CKPT}"
    FLASHRT_QWEN36_LONG_KV_CACHE=fp8
  )
  if command -v flashcli >/dev/null 2>&1; then
    serve_cmd=(flashcli serve qwen36-27b-nvfp4)
  else
    serve_cmd=(python3 -m flashcli.cli serve qwen36-27b-nvfp4)
    serve_env+=(PYTHONPATH="${FLASHCLI_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}")
  fi
  serve_cmd+=(
    --bundle "${BUNDLE}"
    --checkpoint "${CHECKPOINT}"
    --host "${HOST}"
    --port "${PORT}"
    --K "${K}"
    --max-seq "${MAX_SEQ}"
    --warmup-preset "${WARMUP_PRESET}"
    --no-auto-install
  )
  server_cmd="$(printf '%q ' env "${serve_env[@]}" "${serve_cmd[@]}")"
  started="$(date -Iseconds 2>/dev/null || date)"

  log "Starting flashcli + FlashRT (checkpoint=${CHECKPOINT}) …"
  bash "${RUN_BG}" --name "${job}" --cwd "${FLASHCLI_ROOT}" -- \
    env "${serve_env[@]}" \
    "${serve_cmd[@]}" \
    >>"${workdir}/serve.log" 2>&1

  health_s="$(wait_health "${PORT}" "${HEALTH_TIMEOUT}" "${workdir}/serve.log")"
  write_manifest_header "${workdir}" "flashcli+FlashRT" "${server_cmd}" "${started}" "${health_s}" \
    "$(jq -n --arg hf_attn "" --arg hf_dtype "" '{stack: "FlashRT"}')"

  run_bench_cases "${workdir}"
  finish_manifest "${workdir}"
  teardown_backend "${job}" "flashcli+FlashRT"
  log "flashcli bench done → ${workdir}"
}

run_pytorch_backend() {
  local workdir="${OUT_DIR}/pytorch_hf"
  local job="${JOB_PREFIX}-pytorch"
  local server_cmd started health_s

  ensure_gpu_exclusive "PyTorch HF"
  mkdir -p "${workdir}"

  local -a serve_cmd=(
    python3 "${HF_SERVER}"
    --checkpoint "${CHECKPOINT}"
    --model-name "${MODEL_NAME}"
    --host "${HOST}"
    --port "${PORT}"
    --max-seq "${MAX_SEQ}"
    --max-output-tokens 16384
    --attn "${HF_ATTN}"
    --dtype "${HF_DTYPE}"
  )
  server_cmd="$(printf '%q ' "${serve_cmd[@]}")"
  started="$(date -Iseconds 2>/dev/null || date)"

  log "Starting PyTorch HF baseline (same checkpoint=${CHECKPOINT}, max_seq=${MAX_SEQ}) …"
  bash "${RUN_BG}" --name "${job}" --cwd "${FLASHCLI_ROOT}" -- \
    "${serve_cmd[@]}" \
    >>"${workdir}/serve.log" 2>&1

  health_s="$(wait_health "${PORT}" "${HEALTH_TIMEOUT}" "${workdir}/serve.log")"
  write_manifest_header "${workdir}" "PyTorch HF" "${server_cmd}" "${started}" "${health_s}" \
    "$(jq -n \
      --arg hf_attn "${HF_ATTN}" \
      --arg hf_dtype "${HF_DTYPE}" \
      '{stack: "transformers", hf_attn: $hf_attn, hf_dtype: $hf_dtype}')"

  run_bench_cases "${workdir}"
  finish_manifest "${workdir}"
  teardown_backend "${job}" "PyTorch HF"
  log "PyTorch HF bench done → ${workdir}"
}

write_report() {
  local -a report_args=(--out "${OUT_DIR}")
  if [[ -d "${OUT_DIR}/flashcli" ]] && [[ -n "$(find "${OUT_DIR}/flashcli" -name '*.metrics.jsonl' -print -quit 2>/dev/null || true)" ]]; then
    report_args+=(--flashcli "${OUT_DIR}/flashcli")
  fi
  if [[ -d "${OUT_DIR}/pytorch_hf" ]] && [[ -n "$(find "${OUT_DIR}/pytorch_hf" -name '*.metrics.jsonl' -print -quit 2>/dev/null || true)" ]]; then
    report_args+=(--pytorch "${OUT_DIR}/pytorch_hf")
  fi
  python3 "${REPORT_PY}" "${report_args[@]}" >"${OUT_DIR}/REPORT.stdout.log" 2>&1 || {
    cat "${OUT_DIR}/REPORT.stdout.log" >&2
    die "Report generation failed"
  }
  log "Report: ${OUT_DIR}/REPORT.md"
  log "JSON:   ${OUT_DIR}/report.json"
}

log "out_dir=${OUT_DIR}  checkpoint=${CHECKPOINT}  max_seq=${MAX_SEQ}  long_tokens=${LONG_TOKENS}"
log "flashcli=${RUN_FLASHCLI}  pytorch_hf=${RUN_PYTORCH}  quick=${QUICK}  short_only=${SHORT_ONLY}"
log "GPU: $(gpu_name)"

if [[ "${REPORT_ONLY}" -eq 1 ]]; then
  write_report
  exit 0
fi

trap cleanup_on_exit INT TERM EXIT

ensure_gpu_exclusive "bench start"
prepare_shared_payloads

if [[ "${RUN_FLASHCLI}" -eq 1 ]]; then
  run_flashcli_backend
fi

if [[ "${RUN_PYTORCH}" -eq 1 ]]; then
  run_pytorch_backend
fi

write_report
log "Done. Artifacts under ${OUT_DIR}"
