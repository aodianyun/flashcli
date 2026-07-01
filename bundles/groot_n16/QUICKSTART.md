# groot_n16 quick start

<p align="right"><a href="QUICKSTART.zh-CN.md">简体中文</a></p>

**Requires**: Linux · NVIDIA **SM120** (Blackwell) · CUDA **13.x** · Python **3.12**  
**Weights**: [nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B) (not in zip)

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/groot_n16/dist"   # use dist/ after pack
```

---

## 1. Build

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

Outputs:

- `bundles/groot_n16/runtime/sm120-cu130-linux-x86_64-py312/*.so`
- `bundles/groot_n16/flash_rt/`
- `bundles/groot_n16/.build/manifest-overlay.json`

Skip cmake if FlashRT is already built:

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" --pack-only
```

---

## 2. Pack

```bash
bash bundles/groot_n16/pack.sh
```

Outputs under `bundles/groot_n16/dist/`:

- `flashcli-bundle.json` (merged manifest)
- `runtime/sm120-cu130-linux-x86_64-py312/*.so`
- `run.py`, `_groot_*.py`, `flash_rt/`

---

## 3. Validate

```bash
flashcli bundle validate bundles/groot_n16/dist
```

---

## 4. Pull weights / run

```bash
export HF_ENDPOINT=https://hf-mirror.com   # optional mirror

flashcli pull bundles/groot_n16/dist

flashcli run bundles/groot_n16/dist \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg

# Smoke without images (random placeholder frames):
flashcli run bundles/groot_n16/dist \
  --embodiment-tag gr1 \
  --num-views 1
```

---

## 5. Benchmark

```bash
flashcli run bundles/groot_n16/dist \
  --embodiment-tag gr1 \
  --num-views 1 \
  --benchmark 5
```
