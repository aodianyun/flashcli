#!/usr/bin/env bash
# Native (no-Python) smoke test for pi05_libero_nexus.
#
#   bash smoke_native.sh [BUNDLE_DIR]
#
# Requires: a GPU host with the bundle's runtime cell staged, and `flashcli`
# (override with FLASHCLI_BIN=/path/to/flashcli). Weights are pulled once.
set -euo pipefail

BUNDLE="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BIN="${FLASHCLI_BIN:-flashcli}"
PORT="${PORT:-8099}"
PROMPT="${PROMPT:-pick up the red block and place it in the tray}"

echo "== flashcli =="
"$BIN" version

echo "== pull =="
"$BIN" pull "$BUNDLE"

echo "== run (native-abi, no Python) =="
"$BIN" run "$BUNDLE" --prompt "$PROMPT" --num-views 2 | tee /tmp/pi05_run.json

echo "== serve =="
"$BIN" serve "$BUNDLE" --host 127.0.0.1 --port "$PORT" &
SVC=$!
trap 'kill "$SVC" 2>/dev/null || true' EXIT

for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
  sleep 1
done
echo -n "substrate: "; curl -s "http://127.0.0.1:${PORT}/v1/substrate"; echo

python3 - "$PORT" <<'PY'
import base64, json, sys, urllib.request
port = sys.argv[1]

def frame(v):
    return {"width": 224, "height": 224, "data": base64.b64encode(bytes([v]) * 224 * 224 * 3).decode()}

body = json.dumps({
    "prompt": "pick up the red block and place it in the tray",
    "state": [0.0] * 8,
    "images": [frame(80), frame(160)],
}).encode()
req = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/act", data=body,
    headers={"Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req))
print("act shape:", res.get("shape"), "n_actions:", len(res.get("actions", [])))
assert res.get("shape", [0, 0])[0] > 0, "empty action chunk"

snap = {"name": "smoke"}
r = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/session/snapshot", data=json.dumps(snap).encode(),
    headers={"Content-Type": "application/json"})
print("snapshot:", json.load(urllib.request.urlopen(r)))
PY

echo "== SMOKE OK =="
