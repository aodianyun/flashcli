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

CTX=""
ROUNDS=12
SKIP=2
OUT=""
CHECKPOINT=""
MODEL=""
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
MAX_SEQ=262208
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
    --max-seq) MAX_SEQ="$2"; shift 2 ;;
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

PAYLOAD="${WORKDIR}/payload.json"
META="${WORKDIR}/payload.meta.json"

log "build payload ctx≈${CTX} out=${OUT_LEN} max_seq=${MAX_SEQ}"
python3 "${MAKE_PAYLOAD}" \
  --checkpoint "${CHECKPOINT}" \
  --model "${MODEL}" \
  --target-prompt-tokens "${CTX}" \
  --max-tokens "${OUT_LEN}" \
  --max-seq "${MAX_SEQ}" \
  --long-prompt-style flashrt \
  --temperature 0 \
  --stream \
  -o "${PAYLOAD}" \
  --meta-output "${META}"

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
  if ! python3 "${STREAM_ONCE}" --url "${URL}" --payload "${PAYLOAD}" -o "${resp}"; then
    log "round ${r} failed"
    continue
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
