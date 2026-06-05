#!/usr/bin/env bash
# HTTP benchmark for one prompt-context tier (FlashRT-agent or flashcli serve).
# vLLM arm uses `vllm bench latency` instead — see codeplan/flash_vllm.md.
#
# Usage:
#   export BENCH_ARM=flashrt   # or leave default
#   bash scripts/bench_qwen36_ctx_http.sh --ctx 512 --rounds 12 --skip 2 \
#     --checkpoint "$CKPT" --model qwen3.6-27b-nvfp4 --port 8000 \
#     --out results/flashrt-512.jsonl
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAKE_PAYLOAD="${SCRIPT_DIR}/bench_qwen_make_payload.py"
STREAM_ONCE="${SCRIPT_DIR}/bench_qwen_curl_stream.py"
SERVE_METRICS_PY="${SCRIPT_DIR}/bench_qwen36_serve_metrics.py"

CTX=""
ROUNDS=12
SKIP=2
OUT=""
CHECKPOINT=""
MODEL=""
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
MAX_SEQ=""
MAX_SEQ_EXPLICIT=0
SERVE_LOG=""
OUT_LEN=128
WORKDIR=""

log() { printf '[ctx-http] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

usage() {
  sed -n '1,20p' "$0" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ctx) CTX="$2"; shift 2 ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --skip) SKIP="$2"; shift 2 ;;
    --checkpoint) CHECKPOINT="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --max-seq) MAX_SEQ="$2"; MAX_SEQ_EXPLICIT=1; shift 2 ;;
    --serve-log) SERVE_LOG="$2"; shift 2 ;;
    --output-len|--max-tokens) OUT_LEN="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -n "${CTX}" ]] || die "--ctx required (32|512|4096|16384|32768|262144)"
[[ -n "${CHECKPOINT}" ]] || die "--checkpoint required"
[[ -n "${MODEL}" ]] || die "--model required"
[[ -n "${OUT}" ]] || die "--out required (jsonl path)"

if [[ -z "${WORKDIR}" ]]; then
  WORKDIR="$(mktemp -d "/tmp/flashcli-ctx-${CTX}-XXXX")"
  trap 'rm -rf "${WORKDIR}"' EXIT
fi
mkdir -p "$(dirname "${OUT}")"

resolve_max_seq() {
  if [[ "${MAX_SEQ_EXPLICIT}" -eq 1 ]]; then
    echo "${MAX_SEQ}"
    return
  fi
  case "${CTX}" in
    32|512) echo 0 ;;
    4096) echo 12288 ;;
    16384) echo 32768 ;;
    32768) echo 33024 ;;
    262144) echo 262208 ;;
    *) echo 8192 ;;
  esac
}

RESOLVED_MAX_SEQ="$(resolve_max_seq)"
PAYLOAD="${WORKDIR}/payload.json"
META="${WORKDIR}/payload.meta.json"

PAYLOAD_ARGS=(
  --checkpoint "${CHECKPOINT}"
  --model "${MODEL}"
  --target-prompt-tokens "${CTX}"
  --max-tokens "${OUT_LEN}"
  --long-prompt-style flashrt
  --temperature 0
  --stream
  -o "${PAYLOAD}"
  --meta-output "${META}"
)
if [[ "${RESOLVED_MAX_SEQ}" -gt 0 ]]; then
  PAYLOAD_ARGS+=(--max-seq "${RESOLVED_MAX_SEQ}")
fi

log "build payload ctx≈${CTX} out=${OUT_LEN} max_seq=${RESOLVED_MAX_SEQ:-auto}"
python3 "${MAKE_PAYLOAD}" "${PAYLOAD_ARGS[@]}"

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
  local metrics_file="${WORKDIR}/serve_metrics.json"
  [[ -f "${log_path}" ]] || return 0
  if ! python3 "${SERVE_METRICS_PY}" \
      --log "${log_path}" --offset "${offset}" --backend flashrt \
      -o "${metrics_file}" 2>/dev/null; then
    return 0
  fi
  BENCH_RESP="${resp}" BENCH_METRICS="${metrics_file}" python3 - <<'PY'
import json
import os
from pathlib import Path

resp = Path(os.environ["BENCH_RESP"])
metrics = json.loads(Path(os.environ["BENCH_METRICS"]).read_text())
if not metrics:
    raise SystemExit(0)
row = json.loads(resp.read_text())
usage = dict(row.get("usage") or {})
bench = dict(row.get("bench") or {})
for k, v in metrics.items():
    if k != "metrics_source" and v is not None:
        usage[k] = v
ttft = metrics.get("ttft_ms") or metrics.get("first_delta_ms")
if ttft is not None:
    bench["server_ttft_ms"] = float(ttft)
    bench["ttft_ms"] = float(ttft)
    bench["ttft_source"] = "engine"
    bench["metrics_source"] = metrics.get("metrics_source")
row["usage"] = usage
row["bench"] = bench
resp.write_text(json.dumps(row, ensure_ascii=False) + "\n")
PY
}

RENDERED="$(python3 -c "import json; print(int(json.load(open('${META}'))['rendered_prompt_tokens']))")"
log "meta: rendered_prompt_tokens=${RENDERED} (target=${CTX})"

URL="http://${HOST}:${PORT}/v1/chat/completions"
: >"${OUT}"

sum_ttft=0 sum_decode=0 sum_wall=0
count=0
scored=0

for ((r = 1; r <= ROUNDS; r++)); do
  resp="${WORKDIR}/r${r}.json"
  export BENCH_ARM="${BENCH_ARM:-flashrt}"
  log_offset=0
  if [[ -n "${SERVE_LOG}" ]]; then
    log_offset="$(serve_log_offset "${SERVE_LOG}")"
  fi
  if ! python3 "${STREAM_ONCE}" --url "${URL}" --payload "${PAYLOAD}" -o "${resp}"; then
    log "round ${r} failed"
    continue
  fi
  if [[ -n "${SERVE_LOG}" ]]; then
    merge_serve_log_metrics "${resp}" "${SERVE_LOG}" "${log_offset}"
  fi
  line="$(python3 - <<PY
import json
from pathlib import Path
d = json.loads(Path("${resp}").read_text())
bench = d.get("bench") or {}
usage = d.get("usage") or {}
ttft = bench.get("ttft_ms") or usage.get("ttft_ms") or usage.get("first_delta_ms")
decode = usage.get("decode_tok_per_s") or usage.get("tok_per_s")
wall = bench.get("wall_ms")
print(json.dumps({
  "round": ${r},
  "rendered_prompt_tokens": ${RENDERED},
  "ttft_ms": ttft,
  "decode_tok_per_s": decode,
  "wall_ms": wall,
  "ttft_source": bench.get("ttft_source"),
}))
PY
)"
  echo "${line}" >>"${OUT}"
  if (( r <= SKIP )); then
    log "round ${r} (warmup, skip)"
    continue
  fi
  ttft="$(echo "${line}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('ttft_ms') or 0)")"
  decode="$(echo "${line}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('decode_tok_per_s') or 0)")"
  wall="$(echo "${line}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('wall_ms') or 0)")"
  if [[ "${ttft}" != "0" && "${ttft}" != "None" ]]; then
    sum_ttft="$(python3 -c "print(${sum_ttft} + float(${ttft}))")"
    scored=$((scored + 1))
  fi
  if [[ "${decode}" != "0" && "${decode}" != "None" ]]; then
    sum_decode="$(python3 -c "print(${sum_decode} + float(${decode}))")"
  fi
  if [[ "${wall}" != "0" && "${wall}" != "None" ]]; then
    sum_wall="$(python3 -c "print(${sum_wall} + float(${wall}))")"
  fi
  count=$((count + 1))
done

if (( scored < 1 )); then
  die "no scored rounds; check server on ${URL}"
fi

mean_ttft="$(python3 -c "print(round(${sum_ttft}/${scored}, 2))")"
mean_decode="$(python3 -c "print(round(${sum_decode}/max(1,${count}), 2))")"
mean_wall="$(python3 -c "print(round(${sum_wall}/max(1,${count}), 2))")"

summary="$(cat <<EOF
{"ctx_target":${CTX},"rendered_prompt_tokens":${RENDERED},"rounds":${ROUNDS},"skip":${SKIP},"scored":${scored},"mean_ttft_ms":${mean_ttft},"mean_decode_tok_per_s":${mean_decode},"mean_wall_ms":${mean_wall}}
EOF
)"
echo "${summary}" | tee -a "${OUT}" >&2
log "done → ${OUT}"
