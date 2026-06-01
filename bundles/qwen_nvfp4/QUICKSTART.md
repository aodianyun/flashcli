# qwen_nvfp4 quick start

<p align="right"><a href="QUICKSTART.zh-CN.md">简体中文</a></p>

**Requires**: Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.10–3.12**  
**Presets**: `qwen3-8b-nvfp4` / `qwen36-27b-nvfp4` (one runtime zip; `bundle_variant` picks weights)

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"   # local dev; omit to use CDN zip
```

---

## 1. Build local bundle (dev)

CDN zips ship `lib/*.so`. A source tree must be built first:

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
flashcli bundle validate "$BUNDLE"
```

Missing `lib/flash_rt_kernels*.so` → `ImportError: flash_rt_kernels` at serve time.

---

## 2. Pull weights

```bash
flashcli pull qwen3-8b-nvfp4  --bundle "$BUNDLE"
flashcli pull qwen36-27b-nvfp4 --bundle "$BUNDLE"
# ~/.flashcli/models/{preset}/checkpoint/
# qwen36 MTP: ~/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8/
```

Restricted network: `export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. Engine (`run`, no HTTP)

```bash
flashcli run qwen3-8b-nvfp4 --bundle "$BUNDLE" \
  --prompt "Hello" --max-tokens 64

flashcli run qwen36-27b-nvfp4 --bundle "$BUNDLE" \
  --prompt "Hello" --max-tokens 64 --K 6
```

---

## 4. HTTP serve

**One GPU → one `flashcli serve` at a time.** Stop qwen3 before starting qwen36.

### qwen3-8b

```bash
flashcli serve qwen3-8b-nvfp4 --bundle "$BUNDLE" \
  --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 \
  --warmup-preset auto
```

### qwen3.6-27b

```bash
flashcli serve qwen36-27b-nvfp4 --bundle "$BUNDLE" \
  --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 \
  --warmup-preset auto
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--max-seq` | 262208 | total context (prompt + generation) |
| `--max-output-tokens` | **16384** | hard cap per request |
| `--default-max-tokens` | 2048 | when client omits `max_tokens` |
| `--K` | 4 (bundle) | MTP speculative K; bench often uses 6 |

**Optional FlashRT tuning** (usually not needed for `flashcli serve`):

- `FLASHRT_QWEN36_LONG_KV_CACHE` — long-context KV format; default is already **`fp8`**. Set `tq` only to try TurboQuant.
- `FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ` — prompt length threshold for the FP8-KV path when using raw FlashRT server. **flashcli passes `route_min_seq=0` by default**, which overrides this env and routes even short prompts through the long path (see serve logs: `route=long`).

---

## 5. curl smoke test

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-27b-nvfp4",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512,
    "temperature": 0,
    "stream": true
  }'

curl -s http://127.0.0.1:8000/health | jq
```

Request `max_tokens` above `--max-output-tokens` → HTTP 400.

---

## 6. HTTP benchmark

```bash
export CKPT_QWEN3=~/.flashcli/models/qwen3-8b-nvfp4/checkpoint
export CKPT_QWEN36=~/.flashcli/models/qwen36-27b-nvfp4/checkpoint

bash scripts/bench_qwen_curl.sh --qwen3-only --rounds 5

# qwen36 对标 FlashRT 文档（serve 在 8000，需 --max-seq 262208）
QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 \
  bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 \
  --rounds 12 --skip-first 2
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ImportError: flash_rt_kernels` | build bundle; check `lib/` matches SM/CUDA/Python |
| `max_tokens must be <= N` | raise `--max-output-tokens` or lower request `max_tokens` |
| slow first request | new graph bucket; retry is usually faster |
| stale CDN runtime | `--bundle bundles/qwen_nvfp4` after local rebuild |

Release: `bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean` → update both Qwen presets in `models.yaml`.
