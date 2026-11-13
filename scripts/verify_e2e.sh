#!/usr/bin/env bash
# Tier 2/3 acceptance: drive the real binaries (CLI + flashserver API).
#
#   bash scripts/verify_e2e.sh              # offline tier (local fixtures)
#   bash scripts/verify_e2e.sh --network    # + live FlashHub checks
#   bash scripts/verify_e2e.sh --no-build   # reuse dist/go binaries
#
# Tier 1 (development) is `pytest tests/` + `cd go && go test ./...`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK=0
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --network) NETWORK=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

case "$(uname -s)" in
  Linux) : ;;
  *) echo "acceptance tests run on Linux (use WSL on Windows)" >&2; exit 2 ;;
esac

if [ "$BUILD" = 1 ]; then
  bash "$ROOT/scripts/build_go.sh" "$ROOT/dist/go"
fi

export FLASHCLI_GO_BIN="${FLASHCLI_GO_BIN:-$ROOT/dist/go/flashcli-linux-amd64}"
export FLASHSERVER_BIN="${FLASHSERVER_BIN:-$ROOT/dist/go/flashserver-linux-amd64}"
export FLASHCLI_ACCEPTANCE=1
export FLASHCLI_ACCEPTANCE_HOME="${FLASHCLI_ACCEPTANCE_HOME:-/tmp/flashcli-acceptance}"
if [ "$NETWORK" = 1 ]; then
  export FLASHCLI_ACCEPTANCE_NETWORK=1
fi

[ -x "$FLASHCLI_GO_BIN" ] || { echo "missing $FLASHCLI_GO_BIN" >&2; exit 2; }
[ -x "$FLASHSERVER_BIN" ] || { echo "missing $FLASHSERVER_BIN" >&2; exit 2; }

PY="${PYTHON_BIN:-python3}"
echo "[e2e] flashcli=$FLASHCLI_GO_BIN"
echo "[e2e] flashserver=$FLASHSERVER_BIN"
echo "[e2e] network=$NETWORK home=$FLASHCLI_ACCEPTANCE_HOME"
"$PY" -m pytest "$ROOT/tests/acceptance" -q
