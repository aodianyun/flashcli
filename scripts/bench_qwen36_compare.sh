#!/usr/bin/env bash
# Qwen36 bench orchestrator (single entry). See scripts/README.bench_qwen36.md
#
# Smoke FlashRT:  bash scripts/bench_qwen36_compare.sh --quick --flashcli-only
# Smoke vLLM:     bash scripts/bench_qwen36_compare.sh --quick --pytorch-only --vllm --hf-checkpoint <FP8>
# Full compare:   bash scripts/bench_qwen36_compare.sh --comparable --vllm --hf-checkpoint <FP8>
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
# PyTorch baseline stack: hf = bench_qwen36_hf_server.py ; vllm = vllm serve (recommended).
PYTORCH_STACK="${PYTORCH_STACK:-hf}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"
# vLLM: avoid broken flash-attn .so (common with torch 2.12+cu130).
VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND:-TORCH_SDPA}"
VLLM_USE_V1="${VLLM_USE_V1:-0}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-}"
VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.88}"
VLLM_TORCH_COMPILE_LEVEL="${VLLM_TORCH_COMPILE_LEVEL:-0}"
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
# PyTorch HF cannot load NVFP4 linear_attn; use official FP8 for the baseline arm.
HF_CHECKPOINT="${HF_CHECKPOINT:-${HOME}/.flashcli/models/qwen36-27b-fp8/checkpoint}"
HF_MODEL_NAME="${HF_MODEL_NAME:-qwen3.6-27b-fp8}"
MTP_CKPT="${MTP_CKPT:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8}"
OUT_DIR="${OUT_DIR:-}"
PAYLOAD_DIR=""
SERVE_PID_FILE=""

usage() {
  cat <<EOF
Usage: bash scripts/bench_qwen36_compare.sh [OPTIONS]

Serial flow per backend: start serve → wait /health → bench_qwen_curl → stop serve → next.

  --comparable         short+long; 12 rounds skip 2; max_tokens ${SHORT_MAX_TOKENS}/${LONG_MAX_TOKENS}; warmup auto
  --quick              short only; 3 rounds; skip-first 1; max-seq ${QUICK_MAX_SEQ}
  --rounds N --skip-first K   (defaults: ${ROUNDS} / ${SKIP_FIRST})
  --short-only         skip long-context case
  --flashcli-only / --pytorch-only / --report-only
  --checkpoint PATH     FlashRT weights (default: NVFP4 pull path)
  --hf-checkpoint PATH  PyTorch baseline weights (default: Qwen3.6-27B-FP8)
  --hf-model-name NAME  OpenAI API model id (default: ${HF_MODEL_NAME})
  --vllm                Baseline: vLLM OpenAI server (recommended)
  --hf-server           Baseline: minimal transformers server (debug only)
  --max-seq N  --out-dir DIR  --help

Full workflow: scripts/README.bench_qwen36.md
EOF
}

log() { printf '[qwen36-compare] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --flashcli-only) RUN_PYTORCH=0; shift ;;
    --pytorch-only|--hf-only) RUN_FLASHCLI=0; shift ;;
    --report-only) REPORT_ONLY=1; shift ;;
    --comparable)
      QUICK=0
      SHORT_ONLY=0
      ROUNDS=12
      SKIP_FIRST=2
      BENCH_PROFILE=comparable
      # Match codeplan/bench_report: serve CUDA-graph warmup before HTTP rounds.
      WARMUP_PRESET=auto
      shift
      ;;
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
    --hf-checkpoint) HF_CHECKPOINT="$2"; shift 2 ;;
    --hf-model-name) HF_MODEL_NAME="$2"; shift 2 ;;
    --mtp-checkpoint) MTP_CKPT="$2"; shift 2 ;;
    --hf-attn) HF_ATTN="$2"; shift 2 ;;
    --hf-dtype) HF_DTYPE="$2"; shift 2 ;;
    --vllm) PYTORCH_STACK=vllm; shift ;;
    --hf-server) PYTORCH_STACK=hf; shift ;;
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

if [[ "${SKIP_FIRST}" -ge "${ROUNDS}" ]]; then
  die "--skip-first (${SKIP_FIRST}) must be < --rounds (${ROUNDS})"
fi
SCORED_ROUNDS=$((ROUNDS - SKIP_FIRST))

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

checkpoint_looks_nvfp4() {
  local ckpt="$1"
  [[ -n "${ckpt}" && -f "${ckpt}/config.json" ]] || return 1
  grep -qiE 'nvfp4|compressed.tensors|quant_method.*fp4' "${ckpt}/config.json" 2>/dev/null
}

check_serve_log_fatal() {
  local serve_log="$1"
  local backend="${2:-flashrt}"
  [[ -f "${serve_log}" ]] || return 0
  if grep -q 'Invalid model bundle:' "${serve_log}"; then
    tail -n 20 "${serve_log}" >&2 || true
    die "Bundle not built (missing lib/ flash_rt/). See bundles/qwen_nvfp4/QUICKSTART.md"
  fi
  if grep -qE 'Failed to load checkpoint|Cannot import Qwen3_5|does not recognize this architecture|torchvision::nms|requires .accelerate|torchvision are incompatible|CUDA out of memory|OutOfMemoryError|NVFP4 checkpoint cannot run on HF|flash_attn_2_cuda.*undefined symbol|Engine core initialization failed' "${serve_log}"; then
    tail -n 40 "${serve_log}" >&2 || true
    if grep -q 'flash_attn_2_cuda.*undefined symbol' "${serve_log}" 2>/dev/null; then
      die "vLLM: broken flash-attn vs torch ABI. Run: pip uninstall -y flash-attn  then re-run --vllm (see scripts/README.bench_qwen36.md)"
    fi
    if grep -qE 'finegrained-fp8 kernel requires|revision or a version must be specified' "${serve_log}" 2>/dev/null; then
      die "vLLM FP8: pip install 'kernels>=0.12,<0.13'  (not pip install -U kernels)"
    fi
    if grep -q 'CUDA out of memory' "${serve_log}" 2>/dev/null; then
      die "vLLM OOM on GPU. For --quick use VLLM_MAX_MODEL_LEN=8192 (default after script sync). Ensure no other process uses the GPU."
    fi
    die "Server failed — see serve.log above"
  fi
  # Official Qwen3.6-27B-FP8 also logs linear_attn weight_scale_inv as MISSING (transformers init).
  # Only treat as fatal for FlashRT bundle serve or when the checkpoint path is NVFP4.
  if [[ "${backend}" != "hf" ]] && grep -q 'linear_attn.*| MISSING' "${serve_log}" 2>/dev/null; then
    tail -n 15 "${serve_log}" >&2 || true
    die "NVFP4 checkpoint partial load in HF (linear_attn MISSING). Use --hf-checkpoint with Qwen/Qwen3.6-27B-FP8 for PyTorch baseline, or flashcli+FlashRT for NVFP4."
  fi
  if [[ "${backend}" == "hf" ]] && grep -q 'linear_attn.*| MISSING' "${serve_log}" 2>/dev/null; then
    if checkpoint_looks_nvfp4 "${HF_CHECKPOINT}"; then
      tail -n 15 "${serve_log}" >&2 || true
      die "HF baseline needs Qwen/Qwen3.6-27B-FP8 (ModelScope/HF), not NVFP4. See --hf-checkpoint."
    fi
  fi
}

warn_hf_load_report() {
  local serve_log="$1"
  [[ -f "${serve_log}" ]] || return 0
  if grep -q 'linear_attn.*| MISSING' "${serve_log}" 2>/dev/null; then
    log "  note: transformers LOAD REPORT lists linear_attn scale_inv as MISSING for official FP8 — usually OK if /health succeeded"
    log "  for faster linear-attn: pip install flash-linear-attention causal-conv1d (see transformers log)"
  fi
}

wait_health() {
  local serve_log="$1"
  local backend="${2:-flashrt}"
  local start now elapsed=0 last_hint=0
  start="$(date +%s)"
  log "Step: wait http://${HOST}:${PORT}/health (log: ${serve_log})"
  while true; do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      now="$(date +%s)"
      log "  /health OK ($((now - start))s)"
      echo $((now - start))
      return 0
    fi
    check_serve_log_fatal "${serve_log}" "${backend}"
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

payload_checkpoint() {
  # Tokenizer for long-payload fit: prefer HF FP8 tree when running HF arm.
  if [[ "${RUN_PYTORCH}" -eq 1 && -d "${HF_CHECKPOINT}" ]]; then
    echo "${HF_CHECKPOINT}"
  else
    echo "${CHECKPOINT}"
  fi
}

prepare_shared_payloads() {
  local tok_ckpt
  tok_ckpt="$(payload_checkpoint)"
  mkdir -p "${PAYLOAD_DIR}"
  log "Step: build payloads (max_seq=${MAX_SEQ}, tokenizer=${tok_ckpt})"
  local payload_model="${MODEL_NAME}"
  [[ "${RUN_PYTORCH}" -eq 1 ]] && payload_model="${HF_MODEL_NAME}"
  jq -n \
    --arg model "${payload_model}" \
    --arg content "${SHORT_PROMPT}" \
    --argjson max_tokens "${SHORT_MAX_TOKENS}" \
    '{
      model: $model,
      messages: [{role: "user", content: $content}],
      max_tokens: $max_tokens,
      temperature: 0,
      stream: true,
      enable_thinking: false
    }' \
    >"${PAYLOAD_DIR}/qwen36_short.json"
  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    log "  qwen36_short.json only"
    return 0
  fi
  python3 "${MAKE_PAYLOAD}" \
    --checkpoint "${tok_ckpt}" \
    --model "${MODEL_NAME}" \
    --target-prompt-tokens "${LONG_TOKENS}" \
    --max-tokens "${LONG_MAX_TOKENS}" \
    --output "${PAYLOAD_DIR}/qwen36_long.json" \
    --long-prompt-style "$(long_prompt_style)" \
    --stream --max-seq "${MAX_SEQ}" --seq-slack 32
}

write_manifest_header() {
  local workdir="$1" backend="$2" server_cmd="$3" started_at="$4" health_wait_s="$5"
  local stack="${6:-}" hf_attn="${7:-}" hf_dtype="${8:-}"
  health_wait_s="${health_wait_s//[^0-9]/}"
  [[ -n "${health_wait_s}" ]] || health_wait_s=0
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
    --arg hf_checkpoint "${HF_CHECKPOINT:-}" \
    --arg mtp_checkpoint "${MTP_CKPT}" \
    --arg payload_dir "${PAYLOAD_DIR}" \
    --arg bundle "${BUNDLE}" \
    --arg stack "${stack}" \
    --arg hf_attn "${hf_attn}" \
    --arg hf_dtype "${hf_dtype}" \
    '{backend: $backend, started_at: $started_at, health_wait_s: $health_wait_s, gpu_name: $gpu_name,
      server_cmd: $server_cmd, host: $host, port: $port, K: $K, max_seq: $max_seq,
      warmup_preset: $warmup_preset, rounds: $rounds, skip_first: $skip_first, profile: $profile,
      long_tokens: $long_tokens, short_only: ($short_only != 0), checkpoint: $checkpoint,
      hf_checkpoint: $hf_checkpoint, mtp_checkpoint: $mtp_checkpoint, payload_dir: $payload_dir,
      bundle: $bundle, shared_weights: true, shared_payloads: true}
      + (if $stack != "" then {stack: $stack} else {} end)
      + (if $hf_attn != "" then {hf_attn: $hf_attn} else {} end)
      + (if $hf_dtype != "" then {hf_dtype: $hf_dtype} else {} end)' >"${workdir}/manifest.json"
}

finish_manifest() {
  local workdir="$1" finished
  finished="$(date -Iseconds 2>/dev/null || date)"
  jq --arg finished "${finished}" '. + {finished_at: $finished}' \
    "${workdir}/manifest.json" >"${workdir}/manifest.json.tmp"
  mv "${workdir}/manifest.json.tmp" "${workdir}/manifest.json"
}

run_bench_cases() {
  local workdir="$1" api_model="${2:-${MODEL_NAME}}"
  if [[ -n "${api_model}" ]]; then
    jq --arg m "${api_model}" '.model = $m' "${PAYLOAD_DIR}/qwen36_short.json" >"${workdir}/qwen36_short.json"
    if [[ "${SHORT_ONLY}" -eq 0 ]]; then
      jq --arg m "${api_model}" '.model = $m' "${PAYLOAD_DIR}/qwen36_long.json" >"${workdir}/qwen36_long.json"
    fi
  else
    cp "${PAYLOAD_DIR}/qwen36_short.json" "${workdir}/qwen36_short.json"
    [[ "${SHORT_ONLY}" -eq 0 ]] && cp "${PAYLOAD_DIR}/qwen36_long.json" "${workdir}/qwen36_long.json"
  fi

  local -a args=(--qwen36-only --rounds "${ROUNDS}" --skip-first "${SKIP_FIRST}"
    --workdir "${workdir}" --skip-payload-build)
  [[ -n "${BENCH_PROFILE}" ]] && args+=(--profile "${BENCH_PROFILE}")
  [[ "${SHORT_ONLY}" -eq 1 ]] && args+=(--skip-qwen36-long)

  log "Step: bench_qwen_curl.sh (short max_tokens=${SHORT_MAX_TOKENS}, long user_tokens=${LONG_TOKENS})"
  export CKPT_QWEN36="${CHECKPOINT}" HOST QWEN36_PORT="${PORT}" QWEN36_MAX_SEQ="${MAX_SEQ}"
  export SERVE_LOG_PATH="${workdir}/serve.log"
  export QWEN36_SERVE_LOG="${SERVE_LOG_PATH}"
  export SERVE_LOG_BACKEND="${SERVE_LOG_BACKEND:-auto}"
  export QWEN36_LONG_PROMPT_TOKENS="${LONG_TOKENS}"
  export SHORT_MAX_TOKENS LONG_MAX_TOKENS
  export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
  export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512
  args+=(
    --qwen36-long-tokens "${LONG_TOKENS}"
    --short-max-tokens "${SHORT_MAX_TOKENS}"
    --long-max-tokens "${LONG_MAX_TOKENS}"
  )
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
  export SERVE_LOG_BACKEND=flashrt
  start_serve "${workdir}" env "${env_args[@]}" "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log" flashrt)"
  write_manifest_header "${workdir}" "flashcli+FlashRT" "${server_cmd}" "${started}" "${health_s}" "FlashRT"
  run_bench_cases "${workdir}" "${MODEL_NAME}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done FlashRT → ${workdir}"
}

vllm_preflight() {
  python3 - <<'PY' || die "vLLM preflight python failed"
import importlib.metadata
import sys

try:
    import flash_attn_2_cuda  # noqa: F401
except ImportError:
    pass
except OSError as exc:
    if "undefined symbol" in str(exc) or "flash_attn" in str(exc):
        print(
            "broken flash-attn CUDA extension (ABI mismatch with installed torch).\n"
            "  pip uninstall -y flash-attn\n"
            "  bash scripts/bench_qwen36_compare.sh ... --vllm ...",
            file=sys.stderr,
        )
        sys.exit(1)
    raise

try:
    kv = importlib.metadata.version("kernels")
except importlib.metadata.PackageNotFoundError:
    print(
        "kernels package missing (FP8 models need it).\n"
        "  pip install 'kernels>=0.12,<0.13'",
        file=sys.stderr,
    )
    sys.exit(1)

from packaging.version import Version

if Version(kv) >= Version("0.13"):
    print(
        f"kernels {kv} is too new for transformers 5.9 (LayerRepository crash).\n"
        "  pip install 'kernels>=0.12,<0.13'",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import transformers  # noqa: F401
except ValueError as exc:
    if "revision or a version must be specified" in str(exc):
        print(
            "transformers failed to import (kernels/transformers mismatch).\n"
            "  pip install 'kernels>=0.12,<0.13'",
            file=sys.stderr,
        )
        sys.exit(1)
    raise
PY
}

vllm_resolve_max_model_len() {
  if [[ -n "${VLLM_MAX_MODEL_LEN}" ]]; then
    echo "${VLLM_MAX_MODEL_LEN}"
    return
  fi
  if [[ "${QUICK}" -eq 1 ]]; then
    echo 8192
    return
  fi
  # Qwen3.6-27B FP8 on ~48GB: 32K+ KV budget often OOMs during vLLM startup profiling.
  if [[ "${MAX_SEQ}" -gt 16384 ]]; then
    log "  vLLM: default --max-model-len 16384 (48GB-safe). Override: VLLM_MAX_MODEL_LEN=${MAX_SEQ}"
    echo 16384
    return
  fi
  echo "${MAX_SEQ}"
}

run_vllm_backend() {
  local workdir="${OUT_DIR}/pytorch_hf"
  mkdir -p "${workdir}"
  local vllm_max_len
  vllm_max_len="$(vllm_resolve_max_model_len)"

  [[ -d "${HF_CHECKPOINT}" ]] || die "HF checkpoint not found: ${HF_CHECKPOINT}"
  command -v vllm >/dev/null 2>&1 || die "vllm not in PATH. Install: pip install -U vllm (needs Qwen3.6 support in your vLLM build)"
  vllm_preflight
  if [[ "${SHORT_ONLY}" -eq 0 && "${MAX_SEQ}" -gt "${vllm_max_len}" ]]; then
    log "  WARN: vLLM --max-model-len=${vllm_max_len} < bench max_seq=${MAX_SEQ}; long-context case may fail. Use --short-only for vLLM baseline on 48GB."
  fi

  local -a cmd=(
    vllm serve "${HF_CHECKPOINT}"
    --host "${HOST}"
    --port "${PORT}"
    --max-model-len "${vllm_max_len}"
    --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION}"
    --served-model-name "${HF_MODEL_NAME}"
    --trust-remote-code
    --enforce-eager
  )
  if [[ -n "${VLLM_EXTRA_ARGS}" ]]; then
    # shellcheck disable=SC2206
    local extra=( ${VLLM_EXTRA_ARGS} )
    cmd+=("${extra[@]}")
  fi

  local started server_cmd health_s
  started="$(date -Iseconds 2>/dev/null || date)"
  server_cmd="$(printf '%q ' "${cmd[@]}")"

  log "━━ PyTorch baseline (vLLM) ━━"
  log "  vllm: max-model-len=${vllm_max_len} gpu_mem=${VLLM_GPU_MEMORY_UTILIZATION} VLLM_USE_V1=${VLLM_USE_V1} attention=${VLLM_ATTENTION_BACKEND} compile_level=${VLLM_TORCH_COMPILE_LEVEL}"
  export SERVE_LOG_BACKEND=vllm
  start_serve "${workdir}" env \
    VLLM_USE_V1="${VLLM_USE_V1}" \
    VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND}" \
    VLLM_TORCH_COMPILE_LEVEL="${VLLM_TORCH_COMPILE_LEVEL}" \
    PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
    "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log" hf)"
  write_manifest_header "${workdir}" "PyTorch vLLM" "${server_cmd}" "${started}" "${health_s}" \
    "vllm" "" ""
  run_bench_cases "${workdir}" "${HF_MODEL_NAME}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done vLLM baseline → ${workdir}"
}

run_hf_transformers_backend() {
  local workdir="${OUT_DIR}/pytorch_hf"
  mkdir -p "${workdir}"

  [[ -d "${HF_CHECKPOINT}" ]] || die "HF checkpoint not found: ${HF_CHECKPOINT}
  huggingface-cli download Qwen/Qwen3.6-27B-FP8 --local-dir ${HF_CHECKPOINT}"

  local -a cmd=(
    python3 "${HF_SERVER}"
    --checkpoint "${HF_CHECKPOINT}"
    --model-name "${HF_MODEL_NAME}"
    --host "${HOST}" --port "${PORT}"
    --max-seq "${MAX_SEQ}" --max-output-tokens 16384
    --attn "${HF_ATTN}" --dtype "${HF_DTYPE}"
  )
  local started server_cmd health_s
  started="$(date -Iseconds 2>/dev/null || date)"
  server_cmd="$(printf '%q ' "${cmd[@]}")"

  log "━━ PyTorch baseline (transformers HF server) ━━"
  log "  tip: for production-like baseline use --vllm instead of this minimal server"
  export SERVE_LOG_BACKEND=hf
  start_serve "${workdir}" "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log" hf)"
  warn_hf_load_report "${workdir}/serve.log"
  write_manifest_header "${workdir}" "PyTorch HF (transformers)" "${server_cmd}" "${started}" "${health_s}" \
    "transformers" "${HF_ATTN}" "${HF_DTYPE}"
  run_bench_cases "${workdir}" "${HF_MODEL_NAME}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done transformers HF → ${workdir}"
}

run_pytorch_backend() {
  case "${PYTORCH_STACK}" in
    vllm) run_vllm_backend ;;
    hf) run_hf_transformers_backend ;;
    *) die "Unknown PYTORCH_STACK=${PYTORCH_STACK} (use hf or vllm)" ;;
  esac
}

write_report() {
  local -a args=(--out "${OUT_DIR}")
  [[ -d "${OUT_DIR}/flashcli" ]] && args+=(--flashcli "${OUT_DIR}/flashcli")
  [[ -d "${OUT_DIR}/pytorch_hf" ]] && args+=(--pytorch "${OUT_DIR}/pytorch_hf")
  log "Step: report"
  python3 "${REPORT_PY}" "${args[@]}" >"${OUT_DIR}/REPORT.stdout.log" 2>&1
  log "Report: ${OUT_DIR}/REPORT.md"
}

log "out=${OUT_DIR} max_seq=${MAX_SEQ} flashcli=${RUN_FLASHCLI} hf=${RUN_PYTORCH}"
log "bench: cases=$([[ "${SHORT_ONLY}" -eq 1 ]] && echo short-only || echo short+long)  rounds=${ROUNDS} skip_first=${SKIP_FIRST} scored=${SCORED_ROUNDS} profile=${BENCH_PROFILE}"
log "  short: max_tokens=${SHORT_MAX_TOKENS} (decode length)  long: user_tokens=${LONG_TOKENS} max_tokens=${LONG_MAX_TOKENS}"
[[ "${RUN_FLASHCLI}" -eq 1 ]] && log "  FlashRT checkpoint=${CHECKPOINT} warmup=${WARMUP_PRESET}"
if [[ "${RUN_PYTORCH}" -eq 1 ]]; then
  log "  PyTorch baseline: stack=${PYTORCH_STACK} checkpoint=${HF_CHECKPOINT} model=${HF_MODEL_NAME}"
fi
log "GPU: $(gpu_name)"

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
