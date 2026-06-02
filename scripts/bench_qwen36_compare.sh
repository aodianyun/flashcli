#!/usr/bin/env bash
# Qwen3.6-27B NVFP4: FlashRT (flashcli) vs vLLM — one entry for bench + REPORT.md
# See scripts/README.bench_qwen36.md
#
# One-click (short+long, 12 rounds):
#   bash scripts/bench_qwen36_compare.sh --comparable
#
# Short only:  --short-only   |  Long only:  --long-only
# Custom long: --long-tokens 131072 --max-seq 131072
# 16K dual-arm:  bash scripts/bench_qwen36_compare.sh --ctx-16k
# Re-report:   --report-only --out-dir /tmp/qwen36-bench-nvfp4-...
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLASHCLI_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BENCH_CURL="${SCRIPT_DIR}/bench_qwen_curl.sh"
MAKE_PAYLOAD="${SCRIPT_DIR}/bench_qwen_make_payload.py"
PAYLOAD_META="${SCRIPT_DIR}/bench_qwen_payload_meta.py"
REPORT_PY="${SCRIPT_DIR}/bench_qwen36_report.py"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
K=""
MAX_SEQ="${MAX_SEQ:-262208}"
WARMUP_PRESET="${WARMUP_PRESET:-auto}"
ROUNDS="${ROUNDS:-12}"
SKIP_FIRST="${SKIP_FIRST:-2}"
BENCH_PROFILE=""
K_EXPLICIT=0
WARMUP_EXPLICIT=0
LONG_TOKENS="${LONG_TOKENS:-262144}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"
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
LONG_ONLY=0
QUICK=0
QUICK_MAX_SEQ="${QUICK_MAX_SEQ:-32768}"
REUSE_RUNNING_SERVE="${REUSE_RUNNING_SERVE:-1}"
MAX_SEQ_EXPLICIT=0
GPU_SETTLE_EXPLICIT=0
RUN_FLASHCLI=1
RUN_VLLM=1
REPORT_ONLY=0
KEEP_SERVER=0
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-1800}"
GPU_SETTLE_SEC="${GPU_SETTLE_SEC:-8}"

BUNDLE="${BUNDLE:-${FLASHCLI_ROOT}/bundles/qwen_nvfp4}"
CHECKPOINT="${CHECKPOINT:-${CKPT_QWEN36:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/checkpoint}}"
VLLM_CHECKPOINT="${VLLM_CHECKPOINT:-${CHECKPOINT}}"
VLLM_MODEL_NAME="${VLLM_MODEL_NAME:-${MODEL_NAME}}"
MTP_CKPT="${MTP_CKPT:-${HOME}/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8}"
OUT_DIR="${OUT_DIR:-}"
PAYLOAD_DIR=""
SERVE_PID_FILE=""
VLLM_MAX_LEN=""
VLLM_SKIP_LONG=0
VLLM_ARM_FAILED=0
PAYLOAD_SEQ_SLACK="${PAYLOAD_SEQ_SLACK:-32}"
BENCH_STREAM="${BENCH_STREAM:-1}"
FLASHRT_SERVE_MAX_SEQ="${FLASHRT_SERVE_MAX_SEQ:-}"
FLASHRT_SERVE_MAX_SEQ_EXPLICIT=0
BENCH_ISOLATE_ROUNDS=""

usage() {
  cat <<EOF
Usage: bash scripts/bench_qwen36_compare.sh [OPTIONS]

Orchestrates FlashRT (flashcli serve) and vLLM on the same NVFP4 weights and HTTP payloads.
Output: OUT_DIR/REPORT.md  (default OUT_DIR=/tmp/qwen36-bench-nvfp4-<timestamp>)

Context cases (pick one scope; default without --short-only/--long-only = both):
  --short-only          Only short-context bench (qwen36_short)
  --long-only           Only long-context bench (qwen36_long)
  --long-tokens N       Long prompt user tokens (default: ${LONG_TOKENS})
  --max-seq N           Payload fit + vLLM max-model-len (default: ${MAX_SEQ})
  --flashrt-serve-max-seq N  FlashRT serve --max-seq (default: catalog 262208; omit for manual-equivalent startup)

Presets:
  --comparable          short+long; ${ROUNDS} rounds skip ${SKIP_FIRST}; warmup auto; max_seq ${MAX_SEQ}
  --stress              long prompt repeat-fill (MTP stress; not doc-comparable decode)
  --no-isolate-rounds   Keep hot session across rounds (comparable long default)
  --isolate-rounds      Per-round cache_salt (no cross-round decode warmup)
  --ctx-16k             short+long at 16K payload (max_seq=16384; FlashRT serve=catalog 262208)
  --quick               short only; 3 rounds skip 1; warmup none; max_seq ${QUICK_MAX_SEQ}

Arms:
  --flashcli-only       FlashRT only
  --pytorch-only        vLLM only (alias: same as skipping flashcli)
  --report-only         Regenerate REPORT.md from existing OUT_DIR

Paths:
  --checkpoint PATH     NVFP4 weights (default: flashcli pull path)
  --vllm-checkpoint PATH  vLLM weights (default: same as --checkpoint)
  --model-name NAME     OpenAI model id for both arms (default: ${MODEL_NAME})
  --out-dir DIR         Work root (default: /tmp/qwen36-bench-nvfp4-<ts>)
  --bundle --mtp-checkpoint --port --K --rounds --skip-first --profile --help

Full workflow: scripts/README.bench_qwen36.md
EOF
}

bench_cases_label() {
  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    echo "short-only"
  elif [[ "${LONG_ONLY}" -eq 1 ]]; then
    echo "long-only (${LONG_TOKENS} user tokens)"
  else
    echo "short+long"
  fi
}

log() { printf '[qwen36-bench] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

canonical_path() {
  local p="$1"
  if [[ -d "${p}" ]]; then
    (cd "${p}" && pwd)
  elif [[ -f "${p}" ]]; then
    local d b
    d="$(cd "$(dirname "${p}")" && pwd)"
    b="$(basename "${p}")"
    echo "${d}/${b}"
  else
    echo "${p}"
  fi
}

bundle_is_ready() {
  local root="$1"
  [[ -f "${root}/flashcli-bundle.json" && -d "${root}/lib" && -d "${root}/flash_rt" ]]
}

resolve_default_bundle() {
  local -a candidates=()
  local c py_root found

  if [[ -n "${BUNDLE:-}" ]]; then
    candidates+=("$(canonical_path "${BUNDLE}")")
  fi
  candidates+=("$(canonical_path "${FLASHCLI_ROOT}/bundles/qwen_nvfp4")")

  py_root="$(
    python3 - <<'PY' 2>/dev/null || true
try:
    from flashcli.models.registry import get_preset
    from flashcli.bundle.zip import resolve_cached_zip_bundle_root

    p = get_preset("qwen36-27b-nvfp4")
    r = resolve_cached_zip_bundle_root(p)
    if r is not None:
        print(r)
except Exception:
    pass
PY
  )"
  [[ -n "${py_root}" ]] && candidates+=("${py_root}")

  while IFS= read -r found; do
    [[ -n "${found}" ]] && candidates+=("$(dirname "${found}")")
  done < <(
    find "${HOME}/.flashcli/bundles" -name flashcli-bundle.json 2>/dev/null \
      | grep -E 'qwen_nvfp4|qwen36-27b-nvfp4' | sort -r
  )

  for c in "${candidates[@]}"; do
    [[ -n "${c}" ]] || continue
    if bundle_is_ready "${c}"; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

ensure_flashrt_bundle() {
  local bundle_root resolved
  bundle_root="$(canonical_path "${BUNDLE}")"
  if bundle_is_ready "${bundle_root}"; then
    BUNDLE="${bundle_root}"
    return 0
  fi
  resolved="$(resolve_default_bundle || true)"
  if [[ -n "${resolved}" ]] && bundle_is_ready "${resolved}"; then
    log "Bundle: using ${resolved}"
    BUNDLE="${resolved}"
    return 0
  fi
  die "FlashRT bundle not ready: ${BUNDLE}
  Build: bash bundles/qwen_nvfp4/build.sh --repo-root \$FLASHRT_REPO
  Or:   flashcli bundle sync qwen36-27b-nvfp4
  Or:   export BUNDLE=/root/.flashcli/bundles/qwen36-27b-nvfp4/zip/.../extracted/flashcli-bundle-qwen_nvfp4-.../"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --flashcli-only) RUN_VLLM=0; shift ;;
    --pytorch-only|--vllm-only) RUN_FLASHCLI=0; shift ;;
    --report-only) REPORT_ONLY=1; shift ;;
    --comparable)
      QUICK=0
      SHORT_ONLY=0
      LONG_ONLY=0
      ROUNDS=12
      SKIP_FIRST=2
      BENCH_PROFILE=comparable
      WARMUP_PRESET=auto
      WARMUP_EXPLICIT=1
      K="${K:-6}"
      K_EXPLICIT=1
      shift
      ;;
    --ctx-16k)
      QUICK=0
      SHORT_ONLY=0
      LONG_ONLY=0
      MAX_SEQ=16384
      MAX_SEQ_EXPLICIT=1
      ROUNDS=12
      SKIP_FIRST=2
      BENCH_PROFILE=comparable
      WARMUP_PRESET=auto
      WARMUP_EXPLICIT=1
      K="${K:-6}"
      K_EXPLICIT=1
      shift
      ;;
    --quick)
      QUICK=1
      SHORT_ONLY=1
      LONG_ONLY=0
      ROUNDS=3
      SKIP_FIRST=1
      WARMUP_PRESET=none
      [[ "${MAX_SEQ_EXPLICIT}" -eq 0 ]] && MAX_SEQ="${QUICK_MAX_SEQ}"
      shift
      ;;
    --short-only) SHORT_ONLY=1; LONG_ONLY=0; shift ;;
    --long-only) LONG_ONLY=1; SHORT_ONLY=0; shift ;;
    --stress) BENCH_PROFILE=stress; shift ;;
    --no-isolate-rounds) BENCH_ISOLATE_ROUNDS=0; shift ;;
    --isolate-rounds) BENCH_ISOLATE_ROUNDS=1; shift ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --skip-first) SKIP_FIRST="$2"; shift 2 ;;
    --long-tokens|--qwen36-long-tokens) LONG_TOKENS="$2"; shift 2 ;;
    --profile) BENCH_PROFILE="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT="$2"; VLLM_CHECKPOINT="$2"; shift 2 ;;
    --vllm-checkpoint) VLLM_CHECKPOINT="$2"; shift 2 ;;
    --hf-checkpoint) VLLM_CHECKPOINT="$2"; shift 2 ;;
    --model-name) MODEL_NAME="$2"; VLLM_MODEL_NAME="$2"; shift 2 ;;
    --hf-model-name) VLLM_MODEL_NAME="$2"; shift 2 ;;
    --vllm-model-name) VLLM_MODEL_NAME="$2"; shift 2 ;;
    --mtp-checkpoint) MTP_CKPT="$2"; shift 2 ;;
    --vllm) shift ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --K) K="$2"; K_EXPLICIT=1; shift 2 ;;
    --max-seq) MAX_SEQ="$2"; MAX_SEQ_EXPLICIT=1; shift 2 ;;
    --flashrt-serve-max-seq) FLASHRT_SERVE_MAX_SEQ="$2"; FLASHRT_SERVE_MAX_SEQ_EXPLICIT=1; shift 2 ;;
    --warmup-preset) WARMUP_PRESET="$2"; WARMUP_EXPLICIT=1; shift 2 ;;
    --keep-server) KEEP_SERVER=1; shift ;;
    --reuse-serve) REUSE_RUNNING_SERVE=1; shift ;;
    --no-reuse-serve) REUSE_RUNNING_SERVE=0; shift ;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
    --gpu-settle-sec) GPU_SETTLE_SEC="$2"; GPU_SETTLE_EXPLICIT=1; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ "${RUN_FLASHCLI}" -eq 1 || "${RUN_VLLM}" -eq 1 ]] || die "Nothing to run"
[[ "${SHORT_ONLY}" -eq 1 && "${LONG_ONLY}" -eq 1 ]] && die "Use only one of --short-only or --long-only"

# Short-only: same as manual `flashcli serve qwen36-27b-nvfp4 --port 8000 --warmup-preset auto`.
if [[ "${SHORT_ONLY}" -eq 1 && "${LONG_ONLY}" -eq 0 ]]; then
  [[ "${WARMUP_EXPLICIT}" -eq 0 ]] && WARMUP_PRESET=auto
  [[ "${K_EXPLICIT}" -eq 0 ]] && K=""
  [[ "${GPU_SETTLE_EXPLICIT}" -eq 0 ]] && GPU_SETTLE_SEC=2
fi

# --profile comparable without --comparable: still use bench K=6 for FlashRT docs parity.
if [[ "${BENCH_PROFILE}" == "comparable" && "${K_EXPLICIT}" -eq 0 ]]; then
  K=6
fi

if [[ -z "${BENCH_PROFILE}" ]]; then
  if [[ "${LONG_ONLY}" -eq 1 ]]; then
    BENCH_PROFILE=comparable
    [[ "${K_EXPLICIT}" -eq 0 ]] && K="${K:-6}"
    [[ "${WARMUP_EXPLICIT}" -eq 0 ]] && WARMUP_PRESET=auto
    log "  --long-only: default profile=comparable (flashrt seed, K=${K:-6}; use --stress for repeat fill)"
  elif [[ "${SHORT_ONLY}" -eq 0 && "${LONG_ONLY}" -eq 0 ]]; then
    BENCH_PROFILE=comparable
    [[ "${K_EXPLICIT}" -eq 0 ]] && K="${K:-6}"
    [[ "${WARMUP_EXPLICIT}" -eq 0 ]] && WARMUP_PRESET=auto
  fi
fi

if [[ "${SKIP_FIRST}" -ge "${ROUNDS}" ]]; then
  die "--skip-first (${SKIP_FIRST}) must be < --rounds (${ROUNDS})"
fi
SCORED_ROUNDS=$((ROUNDS - SKIP_FIRST))

clamp_long_tokens_to_budget() {
  [[ "${SHORT_ONLY}" -eq 0 ]] || return 0
  local budget=$((MAX_SEQ - LONG_MAX_TOKENS - PAYLOAD_SEQ_SLACK))
  if [[ "${budget}" -lt 1 ]]; then
    die "max_seq=${MAX_SEQ} too small for long max_tokens=${LONG_MAX_TOKENS} slack=${PAYLOAD_SEQ_SLACK}"
  fi
  if [[ "${LONG_TOKENS}" -gt "${budget}" ]]; then
    log "  long-tokens ${LONG_TOKENS} → ${budget} (fit max_seq=${MAX_SEQ} − max_tokens=${LONG_MAX_TOKENS} − slack=${PAYLOAD_SEQ_SLACK})"
    LONG_TOKENS="${budget}"
  fi
}

clamp_long_tokens_to_budget

if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="/tmp/qwen36-bench-nvfp4-$(date +%Y%m%d-%H%M%S)"
fi
OUT_DIR="$(cd "$(dirname "${OUT_DIR}")" && pwd)/$(basename "${OUT_DIR}")"
mkdir -p "${OUT_DIR}"
PAYLOAD_DIR="${OUT_DIR}/payloads"

if [[ "${REPORT_ONLY}" -eq 0 ]]; then
  command -v curl >/dev/null 2>&1 || die "curl not found"
  command -v jq >/dev/null 2>&1 || die "jq not found"
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  [[ -d "${CHECKPOINT}" ]] || die "Checkpoint not found: ${CHECKPOINT}"
  [[ -d "${VLLM_CHECKPOINT}" ]] || die "vLLM checkpoint not found: ${VLLM_CHECKPOINT}"
fi

validate_dual_arm_parity() {
  [[ "${RUN_FLASHCLI}" -eq 1 && "${RUN_VLLM}" -eq 1 ]] || return 0
  local ckpt_flashrt ckpt_vllm
  ckpt_flashrt="$(canonical_path "${CHECKPOINT}")"
  ckpt_vllm="$(canonical_path "${VLLM_CHECKPOINT}")"
  if [[ "${ckpt_flashrt}" != "${ckpt_vllm}" ]]; then
    die "Dual-arm bench requires identical weights: FlashRT=${ckpt_flashrt} vLLM=${ckpt_vllm}"
  fi
  if [[ "${MODEL_NAME}" != "${VLLM_MODEL_NAME}" ]]; then
    die "Dual-arm bench requires identical API model id: FlashRT=${MODEL_NAME} vLLM=${VLLM_MODEL_NAME}"
  fi
}

compute_vllm_plan() {
  VLLM_MAX_LEN="$(vllm_resolve_max_model_len)"
  VLLM_SKIP_LONG=0
  [[ "${RUN_VLLM}" -eq 1 && "${SHORT_ONLY}" -eq 0 ]] || return 0
  local long_budget=$((MAX_SEQ - LONG_MAX_TOKENS - PAYLOAD_SEQ_SLACK))
  if [[ "${long_budget}" -lt 1 ]]; then
    die "max_seq=${MAX_SEQ} too small for long max_tokens=${LONG_MAX_TOKENS}"
  fi
  if [[ "${VLLM_MAX_LEN}" -lt "${long_budget}" ]]; then
    log "  vLLM: max-model-len ${VLLM_MAX_LEN} < long payload budget ${long_budget}; using max_seq=${MAX_SEQ} (no skip — OOM will be reported)"
    VLLM_MAX_LEN="${MAX_SEQ}"
  fi
  if [[ "${MAX_SEQ}" -gt 16384 ]]; then
    log "  vLLM: long ctx max-model-len=${VLLM_MAX_LEN} (256K may OOM on 48GB; override: VLLM_MAX_MODEL_LEN=N)"
  fi
}

record_arm_failure() {
  local workdir="$1" phase="$2" reason="$3" exit_code="${4:-1}"
  mkdir -p "${workdir}"
  jq -n \
    --arg phase "${phase}" \
    --arg reason "${reason}" \
    --argjson exit_code "${exit_code}" \
    --arg failed_at "$(date -Iseconds 2>/dev/null || date)" \
    --arg serve_log "${workdir}/serve.log" \
    '{status: "failed", phase: $phase, reason: $reason, exit_code: $exit_code,
      failed_at: $failed_at, serve_log: $serve_log}' >"${workdir}/arm_failure.json"
}

payload_fit_max_seq() {
  if [[ "${RUN_FLASHCLI}" -eq 1 ]]; then
    echo "${MAX_SEQ}"
    return
  fi
  echo "${VLLM_MAX_LEN}"
}

write_bench_config() {
  local ckpt_flashrt ckpt_vllm weights_match model_match flashrt_k_json payload_cases_json
  ckpt_flashrt="$(canonical_path "${CHECKPOINT}")"
  ckpt_vllm="$(canonical_path "${VLLM_CHECKPOINT}")"
  weights_match=false
  model_match=false
  [[ "${ckpt_flashrt}" == "${ckpt_vllm}" ]] && weights_match=true
  [[ "${MODEL_NAME}" == "${VLLM_MODEL_NAME}" ]] && model_match=true
  if [[ -n "${K}" ]]; then
    flashrt_k_json="${K}"
  else
    flashrt_k_json="null"
  fi
  if [[ -f "${PAYLOAD_DIR}/manifest.json" ]]; then
    payload_cases_json="$(jq -c '.cases // {}' "${PAYLOAD_DIR}/manifest.json")"
  else
    payload_cases_json="{}"
  fi
  jq -n \
    --arg generated_at "$(date -Iseconds 2>/dev/null || date)" \
    --arg gpu "$(gpu_name)" \
    --arg bench_cases "$(bench_cases_label)" \
    --arg checkpoint "${ckpt_flashrt}" \
    --arg vllm_checkpoint "${ckpt_vllm}" \
    --argjson weights_match "${weights_match}" \
    --argjson model_match "${model_match}" \
    --arg model_name "${MODEL_NAME}" \
    --arg vllm_model_name "${VLLM_MODEL_NAME}" \
    --arg short_prompt "${SHORT_PROMPT}" \
    --argjson short_max_tokens "${SHORT_MAX_TOKENS}" \
    --argjson long_max_tokens "${LONG_MAX_TOKENS}" \
    --argjson long_tokens "${LONG_TOKENS}" \
    --argjson max_seq "${MAX_SEQ}" \
    --argjson payload_seq_slack "${PAYLOAD_SEQ_SLACK}" \
    --argjson rounds "${ROUNDS}" \
    --argjson skip_first "${SKIP_FIRST}" \
    --arg profile "${BENCH_PROFILE}" \
    --arg long_prompt_style "$(long_prompt_style)" \
    --argjson temperature 0 \
    --argjson top_p 1 \
    --argjson stream "${BENCH_STREAM}" \
    --argjson enable_thinking false \
    --argjson flashrt_mtp_k "${flashrt_k_json}" \
    --argjson vllm_max_model_len "${VLLM_MAX_LEN:-0}" \
    --argjson vllm_skip_long "${VLLM_SKIP_LONG}" \
    --argjson vllm_arm_failed "${VLLM_ARM_FAILED:-0}" \
    --arg vllm_attention "${VLLM_ATTENTION_BACKEND}" \
    --arg vllm_enforce_eager "true" \
    --arg flashrt_warmup "${WARMUP_PRESET}" \
    --argjson payload_tokens "${payload_cases_json}" \
    '{
      schema: "qwen36-bench-nvfp4/v1",
      generated_at: $generated_at,
      gpu: $gpu,
      bench_cases: $bench_cases,
      weights: {flashrt: $checkpoint, vllm: $vllm_checkpoint, identical: $weights_match},
      api_model: {flashrt: $model_name, vllm: $vllm_model_name, identical: $model_match},
      http_request: {
        short_prompt: $short_prompt,
        short_max_tokens: $short_max_tokens,
        long_max_tokens: $long_max_tokens,
        long_user_tokens_target: $long_tokens,
        temperature: $temperature,
        top_p: $top_p,
        stream: $stream,
        chat_template_kwargs: {enable_thinking: $enable_thinking}
      },
      payload_tokens: $payload_tokens,
      context: {
        max_seq_flashrt: $max_seq,
        payload_seq_slack: $payload_seq_slack,
        long_prompt_style: $long_prompt_style,
        vllm_max_model_len: $vllm_max_model_len,
        vllm_skip_long: ($vllm_skip_long != 0),
        vllm_arm_failed: ($vllm_arm_failed != 0)
      },
      methodology: {
        rounds: $rounds,
        skip_first: $skip_first,
        profile: $profile
      },
      known_asymmetries: [
        "FlashRT uses MTP speculative decode (K=\($flashrt_mtp_k)); vLLM has no MTP in this bench",
        "FlashRT warmup-preset=\($flashrt_warmup); vLLM uses enforce-eager + HTTP warmup rounds only",
        "vLLM attention backend=\($vllm_attention) (FlashRT uses native FlashRT kernels)"
      ]
    }' >"${OUT_DIR}/bench_config.json"
}

if [[ "${REPORT_ONLY}" -eq 0 ]]; then
  validate_dual_arm_parity
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
  for p in $(pgrep -f "flashcli.*serve qwen36|vllm serve|flashcli.cli serve qwen36" 2>/dev/null || true); do
    [[ "${p}" == "$$" ]] && continue
    kill -TERM "${p}" 2>/dev/null || true
  done
  sleep 1
}

stop_serve() {
  [[ "${KEEP_SERVER}" -eq 1 ]] && return 0
  local stopped=0
  if [[ -n "${SERVE_PID_FILE}" && -f "${SERVE_PID_FILE}" ]]; then
    local pid
    pid="$(tr -d '[:space:]' <"${SERVE_PID_FILE}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      log "Stopping serve pid=${pid}"
      kill -TERM "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
      stopped=1
    fi
    rm -f "${SERVE_PID_FILE}"
    SERVE_PID_FILE=""
  fi
  kill_serve_procs
  free_port
  if (( stopped && GPU_SETTLE_SEC > 0 )); then
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
  local backend="${2:-flashrt}"
  [[ -f "${serve_log}" ]] || return 0
  if grep -q 'Invalid model bundle:' "${serve_log}"; then
    tail -n 20 "${serve_log}" >&2 || true
    die "Bundle not built (missing lib/ flash_rt/). See bundles/qwen_nvfp4/QUICKSTART.md"
  fi
  if grep -qE 'Failed to load checkpoint|Cannot import Qwen3_5|does not recognize this architecture|torchvision::nms|requires .accelerate|torchvision are incompatible|CUDA out of memory|OutOfMemoryError|flash_attn_2_cuda.*undefined symbol|Engine core initialization failed' "${serve_log}"; then
    tail -n 40 "${serve_log}" >&2 || true
    if grep -q 'flash_attn_2_cuda.*undefined symbol' "${serve_log}" 2>/dev/null; then
      die "vLLM: broken flash-attn vs torch ABI. Run: pip uninstall -y flash-attn"
    fi
    if grep -qE 'finegrained-fp8 kernel requires|revision or a version must be specified' "${serve_log}" 2>/dev/null; then
      die "vLLM: pip install 'kernels>=0.12,<0.13'"
    fi
    if grep -q 'CUDA out of memory' "${serve_log}" 2>/dev/null; then
      die "vLLM OOM. Lower VLLM_MAX_MODEL_LEN or use --short-only."
    fi
    die "Server failed — see serve.log above"
  fi
  if [[ "${backend}" == "flashrt" ]] && grep -q 'linear_attn.*| MISSING' "${serve_log}" 2>/dev/null; then
    tail -n 15 "${serve_log}" >&2 || true
    die "FlashRT failed to load checkpoint (linear_attn MISSING). Check bundle build and ${CHECKPOINT}"
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
    if (( elapsed - last_hint >= 15 )); then
      last_hint=${elapsed}
      log "  … waiting (${elapsed}s)"
      if [[ "${backend}" == "flashrt" && "${elapsed}" -ge 30 ]]; then
        if grep -q 'Serving .* on http://' "${serve_log}" 2>/dev/null; then
          log "  tip: saw 'Serving …' in log — uvicorn should bind soon; tail -f ${serve_log}"
        elif grep -q 'qwen36 agent warmup:' "${serve_log}" 2>/dev/null; then
          log "  tip: warmup finished, waiting for uvicorn — tail -f ${serve_log}"
        else
          log "  tip: load/warmup in progress (serve.log quiet until done; catalog max_seq ~2–8 min, small --max-seq much slower)"
        fi
      fi
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
    PYTHONUNBUFFERED=1 "$@"
  ) >>"${serve_log}" 2>&1 &
  echo $! >"${SERVE_PID_FILE}"
  log "  pid=$(cat "${SERVE_PID_FILE}")"
}

port_health_model() {
  curl -sf "http://${HOST}:${PORT}/health" 2>/dev/null \
    | jq -r '.model // empty' 2>/dev/null || true
}

can_reuse_flashrt_serve() {
  [[ "${REUSE_RUNNING_SERVE}" -eq 1 ]] || return 1
  local m
  m="$(port_health_model)"
  [[ -n "${m}" ]] && [[ "${m}" == "${MODEL_NAME}" || "${m}" == *qwen3.6* ]]
}

write_payloads_manifest() {
  [[ -d "${PAYLOAD_DIR}" ]] || return 0
  python3 - <<PY
import json
from pathlib import Path
p = Path("${PAYLOAD_DIR}")
cases = {}
for meta in sorted(p.glob("*.meta.json")):
    stem = meta.name[: -len(".meta.json")]
    cases[stem] = json.loads(meta.read_text(encoding="utf-8"))
(p / "manifest.json").write_text(json.dumps({"cases": cases}, indent=2) + "\n", encoding="utf-8")
PY
}

log_payload_tokens() {
  [[ -f "${PAYLOAD_DIR}/manifest.json" ]] || return 0
  log "  payload tokens (ctx=rendered prompt, out=max_output_tokens):"
  jq -r '.cases | to_entries[] |
    "    \(.key): ctx=\(.value.rendered_prompt_tokens // "?") out=\(.value.max_output_tokens // "?") total_budget=\(.value.total_tokens_budget // "?")"' \
    "${PAYLOAD_DIR}/manifest.json" >&2 || true
}

prepare_shared_payloads() {
  mkdir -p "${PAYLOAD_DIR}"
  if [[ "${SHORT_ONLY}" -eq 1 && "${LONG_ONLY}" -eq 0 ]]; then
    log "Step: build payloads (short-only)"
  else
    log "Step: build payloads (cases=$(bench_cases_label), max_seq=${MAX_SEQ}, tokenizer=${CHECKPOINT})"
  fi

  if [[ "${LONG_ONLY}" -eq 0 ]]; then
    jq -n \
      --arg model "${MODEL_NAME}" \
      --arg content "${SHORT_PROMPT}" \
      --argjson max_tokens "${SHORT_MAX_TOKENS}" \
      '{
        model: $model,
        messages: [{role: "user", content: $content}],
        max_tokens: $max_tokens,
        temperature: 0,
        top_p: 1,
        stream: true,
        stream_options: {include_usage: true},
        chat_template_kwargs: {enable_thinking: false}
      }' \
      >"${PAYLOAD_DIR}/qwen36_short.json"
    python3 "${PAYLOAD_META}" \
      --payload "${PAYLOAD_DIR}/qwen36_short.json" \
      --checkpoint "${CHECKPOINT}" \
      --case qwen36_short \
      --meta-output "${PAYLOAD_DIR}/qwen36_short.meta.json" >/dev/null
    log "  qwen36_short.json ($(jq -r '"ctx=\(.rendered_prompt_tokens) out=\(.max_output_tokens)"' "${PAYLOAD_DIR}/qwen36_short.meta.json"))"
  fi

  if [[ "${SHORT_ONLY}" -eq 0 ]]; then
    local payload_max_seq
    payload_max_seq="$(payload_fit_max_seq)"
    python3 "${MAKE_PAYLOAD}" \
      --checkpoint "${CHECKPOINT}" \
      --model "${MODEL_NAME}" \
      --target-prompt-tokens "${LONG_TOKENS}" \
      --max-tokens "${LONG_MAX_TOKENS}" \
      --output "${PAYLOAD_DIR}/qwen36_long.json" \
      --meta-output "${PAYLOAD_DIR}/qwen36_long.meta.json" \
      --long-prompt-style "$(long_prompt_style)" \
      --stream --max-seq "${payload_max_seq}" --seq-slack "${PAYLOAD_SEQ_SLACK}" \
      2>"${PAYLOAD_DIR}/qwen36_long.fit.log"
    log "  qwen36_long.json ($(jq -r '"ctx=\(.rendered_prompt_tokens) out=\(.max_output_tokens) user=\(.user_tokens)"' "${PAYLOAD_DIR}/qwen36_long.meta.json" 2>/dev/null || echo "user_tokens=${LONG_TOKENS} fit max_seq=${payload_max_seq}"))"
  fi
  write_payloads_manifest
  log_payload_tokens
}

long_prompt_style() {
  case "${BENCH_PROFILE}" in
    comparable) echo "flashrt" ;;
    stress) echo "repeat" ;;
    *) echo "${LONG_PROMPT_STYLE:-repeat}" ;;
  esac
}

export_flashrt_serve_env() {
  # Engine reads these at serve load; export before flashcli serve, not only before curl.
  [[ "${SHORT_ONLY}" -eq 0 || "${LONG_ONLY}" -eq 1 ]] || return 0
  export FLASHRT_QWEN36_LONG_KV_CACHE="${FLASHRT_QWEN36_LONG_KV_CACHE:-fp8}"
  export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ="${FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ:-512}"
  # Fixed-shape long decode (FlashRT doc / historical comparable ~69 tok/s on PRO 5000).
  # SM120 agent defaults TQ_*_GRAPH=0 (direct kernels ~29 tok/s at 256K); opt in for bench.
  if [[ "${BENCH_PROFILE}" == "comparable" && "${SHORT_ONLY}" -eq 0 ]]; then
    export FLASHRT_QWEN36_TQ_VERIFY_GRAPH="${FLASHRT_QWEN36_TQ_VERIFY_GRAPH:-1}"
    export FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH="${FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH:-1}"
  fi
}

flashrt_serve_env_args() {
  export_flashrt_serve_env
  if [[ "${SHORT_ONLY}" -eq 0 || "${LONG_ONLY}" -eq 1 ]]; then
    printf '%s\n' \
      "FLASHRT_QWEN36_LONG_KV_CACHE=${FLASHRT_QWEN36_LONG_KV_CACHE}" \
      "FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=${FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ}"
    if [[ "${BENCH_PROFILE}" == "comparable" && "${SHORT_ONLY}" -eq 0 ]]; then
      printf '%s\n' \
        "FLASHRT_QWEN36_TQ_VERIFY_GRAPH=${FLASHRT_QWEN36_TQ_VERIFY_GRAPH}" \
        "FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH=${FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH}"
    fi
  fi
}

resolve_bench_isolate_rounds() {
  if [[ -n "${BENCH_ISOLATE_ROUNDS}" ]]; then
    echo "${BENCH_ISOLATE_ROUNDS}"
    return
  fi
  # comparable long: same-shape decode warmup across rounds; drop hot session after each HTTP call.
  if [[ "${BENCH_PROFILE}" == "comparable" && "${SHORT_ONLY}" -eq 0 ]]; then
    echo 0
  else
    echo 1
  fi
}

write_manifest_header() {
  local workdir="$1" backend="$2" server_cmd="$3" started_at="$4" health_wait_s="$5"
  local stack="${6:-}"
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
    --arg K "${K:-bundle-default}" \
    --argjson max_seq "${MAX_SEQ}" \
    --arg warmup_preset "${WARMUP_PRESET}" \
    --argjson rounds "${ROUNDS}" \
    --argjson skip_first "${SKIP_FIRST}" \
    --arg profile "${BENCH_PROFILE}" \
    --argjson long_tokens "${LONG_TOKENS}" \
    --argjson short_only "${SHORT_ONLY}" \
    --argjson long_only "${LONG_ONLY}" \
    --arg checkpoint "${CHECKPOINT}" \
    --arg vllm_checkpoint "${VLLM_CHECKPOINT}" \
    --arg mtp_checkpoint "${MTP_CKPT}" \
    --arg payload_dir "${PAYLOAD_DIR}" \
    --arg bundle "${BUNDLE}" \
    --arg stack "${stack}" \
    --arg bench_cases "$(bench_cases_label)" \
    --argjson vllm_max_model_len "${VLLM_MAX_LEN:-0}" \
    --argjson vllm_skip_long "${VLLM_SKIP_LONG:-0}" \
    --argjson payload_seq_slack "${PAYLOAD_SEQ_SLACK}" \
    '{backend: $backend, started_at: $started_at, health_wait_s: $health_wait_s, gpu_name: $gpu_name,
      server_cmd: $server_cmd, host: $host, port: $port, K: $K, max_seq: $max_seq,
      warmup_preset: $warmup_preset, rounds: $rounds, skip_first: $skip_first, profile: $profile,
      long_tokens: $long_tokens, short_only: ($short_only != 0), long_only: ($long_only != 0),
      bench_cases: $bench_cases, checkpoint: $checkpoint, vllm_checkpoint: $vllm_checkpoint,
      mtp_checkpoint: $mtp_checkpoint, payload_dir: $payload_dir, bundle: $bundle,
      vllm_max_model_len: $vllm_max_model_len, vllm_skip_long: ($vllm_skip_long != 0),
      payload_seq_slack: $payload_seq_slack,
      shared_weights: true, shared_payloads: true}
      + (if $stack != "" then {stack: $stack} else {} end)' >"${workdir}/manifest.json"
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
  local bench_arm="${SERVE_LOG_BACKEND:-flashrt}"

  if [[ "${LONG_ONLY}" -eq 0 ]]; then
    jq --arg m "${api_model}" '.model = $m' "${PAYLOAD_DIR}/qwen36_short.json" >"${workdir}/qwen36_short.json"
  fi
  if [[ "${SHORT_ONLY}" -eq 0 ]]; then
    jq --arg m "${api_model}" '.model = $m' "${PAYLOAD_DIR}/qwen36_long.json" >"${workdir}/qwen36_long.json"
  fi

  local -a args=(--qwen36-only --rounds "${ROUNDS}" --skip-first "${SKIP_FIRST}"
    --workdir "${workdir}" --skip-payload-build)
  [[ -n "${BENCH_PROFILE}" ]] && args+=(--profile "${BENCH_PROFILE}")
  [[ "${SHORT_ONLY}" -eq 1 ]] && args+=(--skip-qwen36-long)
  [[ "${LONG_ONLY}" -eq 1 ]] && args+=(--skip-short)

  log "Step: bench_qwen_curl.sh ($(bench_cases_label))"
  if [[ -f "${PAYLOAD_DIR}/manifest.json" ]]; then
    log "  shared payloads (ctx=rendered prompt tok, out=max_output_tokens):"
    jq -r '.cases | to_entries[] |
      "    \(.key): ctx=\(.value.rendered_prompt_tokens // "?") out=\(.value.max_output_tokens // "?")"' \
      "${PAYLOAD_DIR}/manifest.json" >&2 || true
  else
    log "  short out=${SHORT_MAX_TOKENS}  long ctx_target=${LONG_TOKENS} out=${LONG_MAX_TOKENS}"
  fi
  export HOST QWEN36_PORT="${PORT}" QWEN36_MAX_SEQ="${MAX_SEQ}"
  export BENCH_PAYLOAD_MANIFEST="${PAYLOAD_DIR}/manifest.json"
  export SERVE_LOG_PATH="${workdir}/serve.log"
  export QWEN36_SERVE_LOG="${SERVE_LOG_PATH}"
  export BENCH_ARM="${bench_arm}"
  export QWEN36_LONG_PROMPT_TOKENS="${LONG_TOKENS}"
  export SHORT_MAX_TOKENS LONG_MAX_TOKENS SHORT_PROMPT BENCH_STREAM=1
  export QWEN36_SEQ_SLACK="${PAYLOAD_SEQ_SLACK}"
  export BENCH_ISOLATE_ROUNDS="$(resolve_bench_isolate_rounds)"
  if [[ "${bench_arm}" == "vllm" ]]; then
    export CKPT_QWEN36="${VLLM_CHECKPOINT}"
  else
    export CKPT_QWEN36="${CHECKPOINT}"
    export_flashrt_serve_env
  fi
  args+=(--short-max-tokens "${SHORT_MAX_TOKENS}" --long-max-tokens "${LONG_MAX_TOKENS}")
  [[ "${SHORT_ONLY}" -eq 0 ]] && args+=(--qwen36-long-tokens "${LONG_TOKENS}")
  # Do not let a failing tee/pipeline skip the vLLM arm (set -euo pipefail).
  set +o pipefail
  bash "${BENCH_CURL}" "${args[@]}" 2>&1 | tee "${workdir}/bench.log"
  local bench_ec=${PIPESTATUS[0]}
  set -o pipefail
  if (( bench_ec != 0 )); then
    die "bench_qwen_curl failed (exit ${bench_ec}); see ${workdir}/bench.log"
  fi
  log "Step: HTTP bench finished → ${workdir}"
}

run_flashcli_backend() {
  local workdir="${OUT_DIR}/flashcli"
  mkdir -p "${workdir}"

  local -a cmd env_args=() started server_cmd health_s
  local flashrt_reused=0 serve_max_seq=""

  [[ -f "${MTP_CKPT}/mtp.safetensors" ]] || die "MTP missing: ${MTP_CKPT}/mtp.safetensors"

  # Payload --max-seq caps HTTP prompt+output; FlashRT serve stays on catalog
  # default (262208) like manual `flashcli serve`. Do NOT pass small --max-seq
  # to FlashRT for 16K benches: max_seq<=32768 → graph_cache_max=1024 (vs 128
  # at 262208), load+warmup can stall 10×+ with almost no serve.log output
  # until uvicorn binds /health.
  if [[ -n "${FLASHRT_SERVE_MAX_SEQ}" ]]; then
    serve_max_seq="${FLASHRT_SERVE_MAX_SEQ}"
  elif [[ "${SHORT_ONLY}" -eq 1 && "${LONG_ONLY}" -eq 0 && "${MAX_SEQ_EXPLICIT}" -eq 1 ]]; then
    serve_max_seq="${MAX_SEQ}"
  fi

  # Same as manual `flashcli serve qwen36-27b-nvfp4 …` — preset resolves bundle/checkpoint/MTP.
  if command -v flashcli >/dev/null 2>&1; then
    cmd=(flashcli serve qwen36-27b-nvfp4)
  else
    cmd=(python3 -m flashcli.cli serve qwen36-27b-nvfp4)
    env_args+=(PYTHONPATH="${FLASHCLI_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}")
  fi
  cmd+=(--host "${HOST}" --port "${PORT}" --warmup-preset "${WARMUP_PRESET}")
  [[ -n "${serve_max_seq}" ]] && cmd+=(--max-seq "${serve_max_seq}")
  [[ -n "${K}" ]] && cmd+=(--K "${K}")

  while IFS= read -r _flashrt_env; do
    [[ -n "${_flashrt_env}" ]] && env_args+=("${_flashrt_env}")
  done < <(flashrt_serve_env_args)

  started="$(date -Iseconds 2>/dev/null || date)"
  if ((${#env_args[@]})); then
    server_cmd="$(printf '%q ' env "${env_args[@]}" "${cmd[@]}")"
  else
    server_cmd="$(printf '%q ' "${cmd[@]}")"
  fi

  log "━━ FlashRT (flashcli) ━━"
  if [[ -n "${serve_max_seq}" ]]; then
    log "  serve max-seq=${serve_max_seq} (payload/vLLM max_seq=${MAX_SEQ})"
  else
    log "  serve max-seq=catalog 262208 (payload/vLLM max_seq=${MAX_SEQ}; matches manual flashcli serve)"
  fi
  export SERVE_LOG_BACKEND=flashrt
  health_s=0
  if can_reuse_flashrt_serve; then
    flashrt_reused=1
    log "  reuse: :${PORT} already up (model=$(port_health_model)) — skip cold start"
    log "  tip: export FLASHCLI_SERVE_LOG=/path/to/tee.log for engine metrics in report"
    SERVE_LOG_PATH="${FLASHCLI_SERVE_LOG:-${workdir}/serve.log}"
    if [[ -n "${FLASHCLI_SERVE_LOG:-}" && -f "${FLASHCLI_SERVE_LOG}" ]]; then
      cp -f "${FLASHCLI_SERVE_LOG}" "${workdir}/serve.log" 2>/dev/null || true
    fi
    server_cmd="(reused running serve on :${PORT})"
  else
    if [[ "${SHORT_ONLY}" -eq 0 || "${LONG_ONLY}" -eq 1 ]]; then
      log "  env: FLASHRT_QWEN36_LONG_KV_CACHE=${FLASHRT_QWEN36_LONG_KV_CACHE:-fp8} FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=${FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ:-512}"
      if [[ "${BENCH_PROFILE}" == "comparable" && "${SHORT_ONLY}" -eq 0 ]]; then
        log "  env: FLASHRT_QWEN36_TQ_VERIFY_GRAPH=${FLASHRT_QWEN36_TQ_VERIFY_GRAPH:-1} FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH=${FLASHRT_QWEN36_TQ_MTP_CHAIN_GRAPH:-1} (fixed-shape graph bench)"
      fi
    fi
    log "  serve: ${server_cmd}"
    if ((${#env_args[@]})); then
      start_serve "${workdir}" env "${env_args[@]}" "${cmd[@]}"
    else
      start_serve "${workdir}" "${cmd[@]}"
    fi
    health_s="$(wait_health "${workdir}/serve.log" flashrt)"
  fi
  write_manifest_header "${workdir}" "flashcli+FlashRT" "${server_cmd}" "${started}" "${health_s}" "FlashRT"
  run_bench_cases "${workdir}" "${MODEL_NAME}"
  finish_manifest "${workdir}"
  # Free :PORT for vLLM (dual-arm must not leave FlashRT bound).
  if [[ "${RUN_VLLM}" -eq 1 ]]; then
    log "Step: stop FlashRT (free :${PORT} for vLLM)"
    stop_serve
  elif [[ "${flashrt_reused}" -eq 0 ]]; then
    stop_serve
  else
    log "  leaving your serve running on :${PORT} (--flashcli-only)"
  fi
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
            "  pip uninstall -y flash-attn",
            file=sys.stderr,
        )
        sys.exit(1)
    raise

try:
    kv = importlib.metadata.version("kernels")
except importlib.metadata.PackageNotFoundError:
    print("kernels package missing.\n  pip install 'kernels>=0.12,<0.13'", file=sys.stderr)
    sys.exit(1)

from packaging.version import Version

if Version(kv) >= Version("0.13"):
    print(
        f"kernels {kv} is too new for transformers 5.9.\n"
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
  if [[ "${SHORT_ONLY}" -eq 1 ]]; then
    echo 8192
    return
  fi
  # Long or short+long: align with FlashRT payload window (same max_seq). May OOM on 48GB.
  echo "${MAX_SEQ}"
}

run_vllm_backend() {
  local workdir="${OUT_DIR}/vllm"
  mkdir -p "${workdir}"
  local vllm_max_len="${VLLM_MAX_LEN}"

  command -v vllm >/dev/null 2>&1 || die "vllm not in PATH (pip install -U vllm)"
  vllm_preflight
  if [[ "${SHORT_ONLY}" -eq 0 && "${MAX_SEQ}" -gt "${vllm_max_len}" ]]; then
    log "  WARN: vLLM --max-model-len=${vllm_max_len} < max_seq=${MAX_SEQ}"
  fi

  local -a cmd=(
    vllm serve "${VLLM_CHECKPOINT}"
    --host "${HOST}"
    --port "${PORT}"
    --max-model-len "${vllm_max_len}"
    --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION}"
    --served-model-name "${VLLM_MODEL_NAME}"
    --trust-remote-code
    --enforce-eager
    --generation-config
    vllm
    --reasoning-parser
    qwen3
    --default-chat-template-kwargs
    '{"enable_thinking": false}'
  )
  if [[ -n "${VLLM_EXTRA_ARGS}" ]]; then
    # shellcheck disable=SC2206
    local extra=( ${VLLM_EXTRA_ARGS} )
    cmd+=("${extra[@]}")
  fi

  local started server_cmd health_s
  started="$(date -Iseconds 2>/dev/null || date)"
  server_cmd="$(printf '%q ' "${cmd[@]}")"

  log "━━ vLLM baseline (same NVFP4 weights) ━━"
  log "  vllm: max-model-len=${vllm_max_len} gpu_mem=${VLLM_GPU_MEMORY_UTILIZATION} checkpoint=${VLLM_CHECKPOINT}"
  export SERVE_LOG_BACKEND=vllm
  start_serve "${workdir}" env \
    VLLM_USE_V1="${VLLM_USE_V1}" \
    VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND}" \
    VLLM_TORCH_COMPILE_LEVEL="${VLLM_TORCH_COMPILE_LEVEL}" \
    PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
    "${cmd[@]}"
  health_s="$(wait_health "${workdir}/serve.log" vllm)"
  write_manifest_header "${workdir}" "vLLM" "${server_cmd}" "${started}" "${health_s}" "vllm"
  run_bench_cases "${workdir}" "${VLLM_MODEL_NAME}"
  finish_manifest "${workdir}"
  stop_serve
  log "Done vLLM → ${workdir}"
}

vllm_failure_reason_from_log() {
  local serve_log="$1"
  local line=""
  [[ -f "${serve_log}" ]] || return 0
  line="$(grep -E 'CUDA out of memory|OutOfMemoryError|Engine core initialization failed|No available memory|Failed to load|max_model_len|max-model-len|KV cache|OOM' "${serve_log}" 2>/dev/null | tail -1 || true)"
  if [[ -n "${line}" ]]; then
    echo "${line}"
    return
  fi
  tail -n 5 "${serve_log}" 2>/dev/null | sed 's/^[[:space:]]*//' | tr '\n' ' '
}

run_vllm_backend_or_record_failure() {
  local workdir="${OUT_DIR}/vllm"
  local ec=0 reason=""
  mkdir -p "${workdir}"
  if ( run_vllm_backend ); then
    return 0
  fi
  ec=$?
  reason="$(vllm_failure_reason_from_log "${workdir}/serve.log")"
  [[ -n "${reason}" ]] || reason="vLLM arm exited with code ${ec} (see ${workdir}/serve.log)"
  record_arm_failure "${workdir}" "serve_or_bench" "${reason}" "${ec}"
  VLLM_ARM_FAILED=1
  log "ERROR: vLLM arm failed (exit ${ec})"
  log "  reason: ${reason}"
  log "  recorded: ${workdir}/arm_failure.json (FlashRT results kept; report will note failure)"
  stop_serve
  return "${ec}"
}

resolve_vllm_workdir() {
  if [[ -d "${OUT_DIR}/vllm" ]]; then
    echo "${OUT_DIR}/vllm"
  elif [[ -d "${OUT_DIR}/pytorch_hf" ]]; then
    echo "${OUT_DIR}/pytorch_hf"
  fi
}

write_report() {
  local -a args=(--out "${OUT_DIR}")
  [[ -d "${OUT_DIR}/flashcli" ]] && args+=(--flashcli "${OUT_DIR}/flashcli")
  local vwd
  vwd="$(resolve_vllm_workdir || true)"
  [[ -n "${vwd}" ]] && args+=(--vllm "${vwd}")
  [[ -f "${OUT_DIR}/vllm/arm_failure.json" || "${VLLM_ARM_FAILED}" -eq 1 ]] && args+=(--allow-arm-failure)
  log "Step: report → ${OUT_DIR}/REPORT.md (engine TTFT/decode from each arm's serve.log)"
  python3 "${REPORT_PY}" "${args[@]}" >"${OUT_DIR}/REPORT.stdout.log" 2>&1
  log "Report: ${OUT_DIR}/REPORT.md"
}

if [[ "${SHORT_ONLY}" -eq 1 && "${LONG_ONLY}" -eq 0 ]]; then
  log "out=${OUT_DIR} cases=$(bench_cases_label) flashcli_serve='flashcli serve qwen36-27b-nvfp4 --port ${PORT} --warmup-preset auto' flashcli=${RUN_FLASHCLI} vllm=${RUN_VLLM}"
else
  log "out=${OUT_DIR} cases=$(bench_cases_label) max_seq=${MAX_SEQ} flashcli=${RUN_FLASHCLI} vllm=${RUN_VLLM}"
fi
log "bench: rounds=${ROUNDS} skip_first=${SKIP_FIRST} scored=${SCORED_ROUNDS} profile=${BENCH_PROFILE:-none}"
if [[ "${SHORT_ONLY}" -eq 1 ]]; then
  log "  short max_tokens=${SHORT_MAX_TOKENS}  (FlashRT serve → bench → vLLM serve → bench)"
else
  log "  short max_tokens=${SHORT_MAX_TOKENS}  long user_tokens=${LONG_TOKENS} long max_tokens=${LONG_MAX_TOKENS}"
fi
if [[ "${RUN_FLASHCLI}" -eq 1 ]]; then
  if [[ -n "${K}" ]]; then
    log "  FlashRT checkpoint=${CHECKPOINT} warmup=${WARMUP_PRESET} K=${K}"
  else
    log "  FlashRT checkpoint=${CHECKPOINT} warmup=${WARMUP_PRESET} K=bundle-default"
  fi
fi
log "GPU: $(gpu_name)"

if [[ "${REPORT_ONLY}" -eq 1 ]]; then
  write_report
  exit 0
fi

compute_vllm_plan
[[ "${RUN_FLASHCLI}" -eq 1 ]] && log "  FlashRT serve=preset qwen36-27b-nvfp4 (manual-equivalent, no --bundle zip)"
[[ "${RUN_VLLM}" -eq 1 ]] && log "  vLLM checkpoint=${VLLM_CHECKPOINT} model=${VLLM_MODEL_NAME} max_model_len=${VLLM_MAX_LEN}"
[[ "${RUN_FLASHCLI}" -eq 1 || "${RUN_VLLM}" -eq 1 ]] || die "No backend to run after vLLM context plan"

trap cleanup_on_exit INT TERM EXIT

prepare_shared_payloads
write_bench_config
if [[ "${RUN_FLASHCLI}" -eq 1 ]]; then
  run_flashcli_backend
fi
if [[ "${RUN_VLLM}" -eq 1 ]]; then
  log "━━ vLLM arm (after FlashRT) ━━"
  run_vllm_backend_or_record_failure || true
fi
write_bench_config
write_report
if [[ "${VLLM_ARM_FAILED}" -eq 1 ]]; then
  log "Finished with vLLM arm failure — see ${OUT_DIR}/vllm/arm_failure.json and ${OUT_DIR}/REPORT.md"
  exit 1
fi
log "All done: ${OUT_DIR}"
