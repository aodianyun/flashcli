#!/usr/bin/env bash
# verify_cache.sh — cache-key parity / hit smoke (GPU-free).
#
# Verifies that the Go host derives the same cache keys as the flashcli-bundle
# protocol, for both remote (FlashHub) and local bundles, with and without
# @variant:
#   remote  -> <repoName>/<version>          (never m.Name, never @variant)
#   local   -> <name>-local-<sha12>/local    (protocol local id)
# and that weights/ tree markers resolve at those keys.
#
# GPU-free: resolves host-side weight caches via `flashcli pull` (no inference).
# Prerequisites are marked SKIP when absent; only real mismatches FAIL.
#
# Usage: FLASHCLI_HOME=~/.flashcli bash scripts/verify_cache.sh
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
# pull <ref> -> prints host-side weight resolution lines (no inference)
pull(){ flashcli pull "$1" 2>&1; }

# protocol python: any bundle venv that has flashcli_bundle, for local-id parity.
PROTO_PY=""
for p in "$H"/runtimes/*/venv/bin/python; do
  [ -x "$p" ] || continue
  PYTHONPATH="${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}" "$p" -c "import flashcli_bundle" 2>/dev/null && { PROTO_PY="$p"; break; }
done
LOCAL_SRC="${FLASHC_LOCAL_BUNDLE:-/app/flashcli/bundles/pi05_libero_nexus}"

echo "================ REMOTE ================"
if [ -f "$H/bundles/qwen_nvfp4/1.0.1/.flashcli_bundle.json" ]; then
  ck "R1 tree key variant-less: bundles/qwen_nvfp4/1.0.1" "true"
  ck "R2 weights base variant-less: models/qwen_nvfp4/1.0.1/checkpoint/qwen3" \
     "[ -d '$H/models/qwen_nvfp4/1.0.1/checkpoint/qwen3' ]"
  ck "R3 @qwen3 pull hits weights cache" \
     "pull flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 | grep -q 'already cached: .*qwen_nvfp4/1.0.1/checkpoint/qwen3'"
  ck "R4 multi-variant without @variant errors" \
     "pull flashcli-bundle/qwen_nvfp4:1.0.1 | grep -qi 'add @variant'"
  wd36=$(python3 -c "import json;print(json.load(open('$H/bundles/qwen_nvfp4/1.0.1/flashcli-bundle.json'))['variants']['qwen36']['weights_dir'])" 2>/dev/null)
  ck "R5 @qwen36 shares base key, weights_dir=$wd36" "[ '$wd36' = 'checkpoint/qwen36' ]"
else
  skip "REMOTE qwen_nvfp4 not synced (run: flashcli pull flashcli-bundle/qwen_nvfp4:1.0.1@qwen3)"
fi
if [ -f "$H/bundles/pi05_libero/1.0.4/.flashcli_bundle.json" ]; then
  ck "R6 single-variant tree key: bundles/pi05_libero/1.0.4" "true"
  ck "R7 pi05_libero:1.0.4 pull hits weights cache" \
     "pull flashcli-bundle/pi05_libero:1.0.4 | grep -q 'already cached: .*pi05_libero/1.0.4/checkpoint'"
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
  if [ -d "$H/models/$ID/local/checkpoint" ]; then
    ck "L3 @abi pull hits local weights cache" \
       "pull $LOCAL_SRC@abi | grep -q 'already cached: .*$ID/local/checkpoint'"
    ck "L4 @exec shares the same local weights key" \
       "pull $LOCAL_SRC@exec | grep -q 'already cached: .*$ID/local/checkpoint'"
  else
    skip "LOCAL weights not cached under new key ($H/models/$ID/local/checkpoint)"
  fi
  ln -sfn "$LOCAL_SRC" /tmp/.flashcli_cache_link.$$
  ID2=$(PYTHONPATH="${FLASHC_LB:-/app/flashcli/flashcli-bundle/src}" "$PROTO_PY" \
        -c "from pathlib import Path;from flashcli_bundle.preset_ref import local_bundle_id;print(local_bundle_id(Path('/tmp/.flashcli_cache_link.$$')))" 2>/dev/null)
  rm -f /tmp/.flashcli_cache_link.$$
  ck "L5 symlinked path -> same local id" "[ '$ID' = '$ID2' ]"
else
  skip "LOCAL parity needs a bundle venv (flashcli_bundle) + a local bundle at $LOCAL_SRC"
fi

echo "================ SUMMARY ================"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" -eq 0 ]
