#!/usr/bin/env bash
# verify_cache.sh — cache-key parity / offline readiness smoke.
#
# Verifies:
#   - remote keys are variant-independent: <repoName>/<version> (no @variant);
#   - local keys follow the flashcli-bundle protocol local id;
#   - a prepared cache is reported ready LOCALLY (models list), i.e. no network;
#   - optionally (VERIFY_CACHE_RUN=1 and a GPU): a cached native bundle still
#     runs with an unreachable HF endpoint, proving offline operation.
#
# Prerequisites are SKIPped when absent; only real mismatches FAIL.
# Usage: bash scripts/verify_cache.sh   (VERIFY_CACHE_RUN=1 to run the GPU check)
set -u

: "${FLASHCLI_HOME:=$HOME/.flashcli}"
H="$FLASHCLI_HOME"
have(){ command -v "$1" >/dev/null 2>&1; }
have flashcli || { echo "error: flashcli not on PATH"; exit 2; }

PASS=0; FAIL=0; SKIP=0
ok(){   printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad(){  printf 'FAIL  %s\n' "$1"; FAIL=$((FAIL+1)); }
skip(){ printf 'SKIP  %s\n' "$1"; SKIP=$((SKIP+1)); }
ck(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }
models(){ flashcli models list 2>&1; }

PROTO_PY=""
for p in "$H"/runtimes/*/venv/bin/python; do
  [ -x "$p" ] || continue
  PYTHONPATH="${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}" "$p" -c "import flashcli_bundle" 2>/dev/null && { PROTO_PY="$p"; break; }
done
LOCAL_SRC="${FLASHC_LOCAL_BUNDLE:-/app/flashcli/bundles/pi05_libero_nexus}"
LIST="$(models 2>/dev/null || true)"

echo "================ REMOTE ================"
if [ -f "$H/bundles/qwen_nvfp4/1.0.1/.flashcli_bundle.json" ]; then
  ck "R1 tree key variant-less: bundles/qwen_nvfp4/1.0.1" "true"
  ck "R2 weights base variant-less: models/qwen_nvfp4/1.0.1/checkpoint/qwen3" \
     "[ -d '$H/models/qwen_nvfp4/1.0.1/checkpoint/qwen3' ]"
  ck "R3 local readiness (models list): @qwen3 weights:cached" \
     "printf '%s' \"\$LIST\" | grep -q 'qwen_nvfp4:1.0.1@qwen3.*weights:cached'"
  ck "R4 multi-variant without @variant errors locally" \
     "flashcli run flashcli-bundle/qwen_nvfp4:1.0.1 --prompt x 2>&1 | grep -qi 'add @variant'"
  wd36=$(python3 -c "import json;print(json.load(open('$H/bundles/qwen_nvfp4/1.0.1/flashcli-bundle.json'))['variants']['qwen36']['weights_dir'])" 2>/dev/null)
  ck "R5 @qwen36 shares base key, weights_dir=$wd36" "[ '$wd36' = 'checkpoint/qwen36' ]"
else
  skip "REMOTE qwen_nvfp4 not synced"
fi
if [ -f "$H/bundles/pi05_libero/1.0.4/.flashcli_bundle.json" ]; then
  ck "R6 single-variant tree key: bundles/pi05_libero/1.0.4" "true"
  ck "R7 local readiness: pi05_libero:1.0.4 weights:cached" \
     "printf '%s' \"\$LIST\" | grep -q 'pi05_libero:1.0.4.*weights:cached'"
else
  skip "REMOTE pi05_libero:1.0.4 not synced"
fi

echo "================ LOCAL ================"
if [ -n "$PROTO_PY" ] && [ -f "$LOCAL_SRC/flashcli-bundle.json" ]; then
  ID=$(PYTHONPATH="${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}" "$PROTO_PY" \
        -c "from pathlib import Path;from flashcli_bundle.preset_ref import local_bundle_id;print(local_bundle_id(Path('$LOCAL_SRC')))" 2>/dev/null)
  echo "  local id = $ID"
  ck "L1 host-local marker at protocol path bundles/<id>/local" \
     "[ -f '$H/bundles/$ID/local/.flashcli_bundle.json' ]"
  ck "L2 protocol reads the host-written marker" \
     "PYTHONPATH='${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}' '$PROTO_PY' -c \"from pathlib import Path;from flashcli_bundle.preset_ref import resolve_local_bundle_preset;from flashcli_bundle.marker import read_preset_marker;import sys;sys.exit(0 if read_preset_marker(resolve_local_bundle_preset(Path('$LOCAL_SRC'),None)) else 1)\""
  ck "L3 local readiness: pi05_libero_nexus weights:cached" \
     "printf '%s' \"\$LIST\" | grep -qE '^pi05_libero_nexus .*weights:cached'"
  ln -sfn "$LOCAL_SRC" /tmp/.flashcli_cache_link.$$
  ID2=$(PYTHONPATH="${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}" "$PROTO_PY" \
        -c "from pathlib import Path;from flashcli_bundle.preset_ref import local_bundle_id;print(local_bundle_id(Path('/tmp/.flashcli_cache_link.$$')))" 2>/dev/null)
  rm -f /tmp/.flashcli_cache_link.$$
  ck "L4 symlinked path -> same local id" "[ '$ID' = '$ID2' ]"
else
  skip "LOCAL parity needs a bundle venv + a local bundle at $LOCAL_SRC"
fi

echo "================ OFFLINE RUN (optional) ================"
if [ "${VERIFY_CACHE_RUN:-0}" = 1 ] && have nvidia-smi && [ -f "$LOCAL_SRC/flashcli-bundle.json" ]; then
  OUT=$(HF_ENDPOINT=http://127.0.0.1:9 timeout 180 \
        flashcli run "$LOCAL_SRC@abi" --warmup 0 --benchmark 1 2>&1 || true)
  ck "O1 cached run works with HF unreachable (offline)" \
     "printf '%s' \"\$OUT\" | grep -q 'already cached'"
  ck "O2 offline run produced a benchmark result" \
     "printf '%s' \"\$OUT\" | grep -q 'benchmark n=1'"
else
  skip "OFFLINE RUN (set VERIFY_CACHE_RUN=1 and provide a GPU)"
fi

echo "================ SUMMARY ================"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" -eq 0 ]
