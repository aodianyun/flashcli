#!/usr/bin/env bash
# Generate the PI0.5 native FP8 calibration artifact for this bundle.
#
# Downloads a real LIBERO observation slice (LeRobot v3, lerobot/libero),
# extracts 2-view frames + state + prompt, then runs the FlashRT native
# calibration C API against the staged substrate to produce:
#   calib/pi05_sm120_fp8.calib
#
# Usage:
#   FLASHRT_REPO=/path/to/FlashRT \
#   bash calibrate_fp8.sh --checkpoint /path/to/pi05_ckpt [,--tokenizer FILE]
#
# Env: HF_ENDPOINT (default https://hf-mirror.com), FLASHRT_REPO, CALIB_STEP,
#      WORK (default /tmp/pi05_calib_work).
# Requires: python3 + pyarrow, ffmpeg, g++ , curl.
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
FLASHRT_REPO="${FLASHRT_REPO:-}"
CHECKPOINT=""
TOKENIZER="${FLASH_RT_PALIGEMMA_TOKENIZER:-$HOME/.cache/flash_rt/paligemma_tokenizer.model}"
STEP="${CALIB_STEP:-15}"
WORK="${WORK:-/tmp/pi05_calib_work}"
DATASET="lerobot/libero"

while [ $# -gt 0 ]; do
  case "$1" in
    --checkpoint) CHECKPOINT="$2"; shift 2 ;;
    --tokenizer) TOKENIZER="$2"; shift 2 ;;
    --dataset) DATASET="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$FLASHRT_REPO" ] || { echo "error: set FLASHRT_REPO" >&2; exit 2; }
[ -n "$CHECKPOINT" ] || { echo "error: --checkpoint DIR required" >&2; exit 2; }
[ -f "$TOKENIZER" ] || { echo "error: tokenizer not found: $TOKENIZER" >&2; exit 2; }

SUB="${BUNDLE_DIR}/runtime/sm120-cu130-linux-x86_64/substrate"
[ -d "$SUB" ] || { echo "error: build the bundle first ($SUB missing)" >&2; exit 2; }

mkdir -p "$WORK/ds" "$WORK/obs"
B="${HF_ENDPOINT}/datasets/${DATASET}/resolve/main"

echo "[calib] downloading LIBERO slice -> $WORK/ds"
curl -fsSL "$B/meta/tasks.parquet" -o "$WORK/ds/tasks.parquet"
curl -fsSL "$B/meta/episodes/chunk-000/file-000.parquet" -o "$WORK/ds/episodes-file-000.parquet"
curl -fsSL "$B/data/chunk-000/file-000.parquet" -o "$WORK/ds/data-file-000.parquet"
curl -fsSL "$B/videos/observation.images.image/chunk-000/file-000.mp4" -o "$WORK/ds/image-file-000.mp4"
curl -fsSL "$B/videos/observation.images.image2/chunk-000/file-000.mp4" -o "$WORK/ds/image2-file-000.mp4"

echo "[calib] extracting observations (step=$STEP)"
python3 "${BUNDLE_DIR}/native_calib/extract_libero_obs.py" "$WORK/ds" "$WORK/obs" "$STEP"

# Build the calibration runner against the bundle substrate.
PI05="$(basename "$(ls "$SUB"/libflashrt_cpp_pi05_c-*.so | head -1)")"
RT="$(basename "$(ls "$SUB"/libflashrt_runtime-*.so | head -1)")"
EX="$(basename "$(ls "$SUB"/libflashrt_exec-*.so | head -1)")"
echo "[calib] compiling runner"
g++ -std=c++17 -O2 "${BUNDLE_DIR}/native_calib/pi05_calib.cpp" -o "$WORK/pi05_calib" \
  -I"${FLASHRT_REPO}/cpp/models/pi05/include" \
  -I"${FLASHRT_REPO}/runtime/include" \
  -I"${FLASHRT_REPO}/exec/include" \
  -L"$SUB" -Wl,-rpath,"$SUB" \
  -l:"$PI05" -l:"$RT" -l:"$EX" -ldl -lpthread

# Shorter SONAME symlinks for the runner's dlopen.
mkdir -p "$WORK/lib"
for f in "$SUB"/*.so; do
  son="$(readelf -d "$f" | sed -n 's/.*SONAME.*\[\(.*\)\].*/\1/p')"
  ln -sf "$f" "$WORK/lib/${son:-$(basename "$f")}"
done

cat > "$WORK/config.json" <<JSON
{
  "io": "native_v2",
  "checkpoint_path": "$CHECKPOINT",
  "tokenizer_model_path": "$TOKENIZER",
  "state_prompt_mode": "fixed",
  "precision": "fp8_e4m3fn",
  "stage_plan": "full",
  "num_views": 2,
  "chunk": 10,
  "state_dim": 8,
  "num_steps": 10,
  "max_prompt_tokens": 64
}
JSON

echo "[calib] running calibration"
mkdir -p "${BUNDLE_DIR}/calib"
LD_LIBRARY_PATH="$WORK/lib" "$WORK/pi05_calib" \
  "$WORK/config.json" "${BUNDLE_DIR}/calib/pi05_sm120_fp8.calib" "$WORK/obs" 256 256
echo "[calib] wrote ${BUNDLE_DIR}/calib/pi05_sm120_fp8.calib"
