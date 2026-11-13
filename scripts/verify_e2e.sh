#!/usr/bin/env bash
# Tier 2/3 acceptance: drive the real binaries (CLI + flashserver API).
#
#   bash scripts/verify_e2e.sh                 # offline tier (local fixtures)
#   bash scripts/verify_e2e.sh --heavy         # + python bundles (installs torch)
#   bash scripts/verify_e2e.sh --heavy --network  # full release gate
#   bash scripts/verify_e2e.sh --no-build      # reuse dist/go binaries
#
# Publishing requires the full gate (--heavy --network): on success this writes
# dist/e2e-pass.json for the current commit, which scripts/release_go.sh
# --upload checks before it will publish.
#
# Tier 1 (development) is `pytest tests/` + `cd go && go test ./...`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK=0
HEAVY=0
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --network) NETWORK=1 ;;
    --heavy) HEAVY=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
if [ "$HEAVY" = 1 ]; then
  export FLASHCLI_ACCEPTANCE_HEAVY=1
fi

[ -x "$FLASHCLI_GO_BIN" ] || { echo "missing $FLASHCLI_GO_BIN" >&2; exit 2; }
[ -x "$FLASHSERVER_BIN" ] || { echo "missing $FLASHSERVER_BIN" >&2; exit 2; }

PY="${PYTHON_BIN:-python3}"
echo "[e2e] flashcli=$FLASHCLI_GO_BIN"
echo "[e2e] flashserver=$FLASHSERVER_BIN"
echo "[e2e] heavy=$HEAVY network=$NETWORK home=$FLASHCLI_ACCEPTANCE_HOME"
"$PY" -m pytest "$ROOT/tests/acceptance" -q

commit="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
mkdir -p "$ROOT/dist"
cat > "$ROOT/dist/e2e-pass.json" <<JSON
{"commit":"$commit","heavy":$([ "$HEAVY" = 1 ] && echo true || echo false),"network":$([ "$NETWORK" = 1 ] && echo true || echo false),"at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
JSON
echo "[e2e] wrote dist/e2e-pass.json (commit $commit heavy=$HEAVY network=$NETWORK)"
