# qwen_nvfp4 quick start

<p align="right"><a href="QUICKSTART.zh-CN.md">简体中文</a></p>

**Requires**: Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.12** (bundle venv; host CLI 3.10+)  
**Refs**: `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` / `@qwen36` (one FlashHub repo; `@variant` picks weights)

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"   # local dev; omit for FlashHub sync
```

---

## 1. Build local bundle (dev)

FlashHub sync puts `.so` under `runtime/<env-key>/`. Local `build.sh` stages to `lib/` first; copy into the matching runtime cell before validate/run:

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen_nvfp4/${ENV_KEY}"
cp bundles/qwen_nvfp4/lib/*.so "bundles/qwen_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

Missing `runtime/<env-key>/flash_rt_kernels*.so` → `ImportError: flash_rt_kernels` at serve time.

---

## 2. Pull weights

```bash
flashcli pull "$BUNDLE@qwen3"
flashcli pull "$BUNDLE@qwen36"
# ~/.flashcli/models/qwen_nvfp4/1.0.1@qwen3/checkpoint/
# qwen36 MTP: ~/.flashcli/models/qwen_nvfp4/1.0.1@qwen36/mtp_fp8/
```

Restricted network: `export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. Engine (`run`, no HTTP)

```bash
flashcli run "$BUNDLE@qwen3" --help
flashcli run "$BUNDLE@qwen36" --help

flashcli run "$BUNDLE@qwen3" --prompt "Hello" --max-tokens 64

flashcli run "$BUNDLE@qwen36" --prompt "Hello" --max-tokens 64 --K 6
```

---

## 4. HTTP serve

**One GPU → one `flashcli serve` at a time.** Stop qwen3 before starting qwen36.

```bash
flashcli serve "$BUNDLE@qwen3" --help
flashcli serve "$BUNDLE@qwen36" --help

flashcli serve "$BUNDLE@qwen3" --host 0.0.0.0 --port 8000

flashcli serve "$BUNDLE@qwen36" --host 0.0.0.0 --port 8000 --K 6
```

| Flag | qwen3 default | qwen36 default | Meaning |
|------|---------------|----------------|---------|
| `--max-seq` | 2048 | 262208 | total context (prompt + generation) |
| `--max-output-tokens` | — | **16384** | hard cap per request (qwen36 serve) |
| `--default-max-tokens` | — | 2048 | when client omits `max_tokens` (qwen36) |
| `--K` | — | 4 | MTP speculative K; bench often uses 6 |

**Optional FlashRT tuning** (usually not needed for `flashcli serve`):

- `FLASHRT_QWEN36_LONG_KV_CACHE` — long-context KV format; default is already **`fp8`**. Set `tq` only to try TurboQuant.
- `FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ` — prompt length threshold for the FP8-KV path when using raw FlashRT server. **flashcli passes `route_min_seq=0` by default**, which overrides this env and routes even short prompts through the long path (see serve logs: `route=long`).

---

## 5. curl smoke test

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen36",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 128,
    "temperature": 0,
    "stream": true
  }'

curl -s http://127.0.0.1:8000/health | jq
```

Request `max_tokens` above `--max-output-tokens` → HTTP 400.

---

## 6. HTTP benchmark

```bash
# Weights under ~/.flashcli/models/qwen_nvfp4/1.0.1@<variant>/; run: flashcli models show "$BUNDLE@qwen3"
export CKPT_QWEN3=~/.flashcli/models/qwen_nvfp4/1.0.1@qwen3/checkpoint
export CKPT_QWEN36=~/.flashcli/models/qwen_nvfp4/1.0.1@qwen36/checkpoint

bash scripts/bench_qwen_curl.sh --qwen3-only --rounds 5

QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 \
  bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 \
  --rounds 12 --skip-first 2
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ImportError: flash_rt_kernels` | build bundle; ensure `runtime/<env-key>/` has `.so` for this SM/CUDA/Python |
| `max_tokens must be <= N` | raise `--max-output-tokens` or lower request `max_tokens` |
| slow first request | new graph bucket; retry is usually faster |
| stale FlashHub runtime | use local path `bundles/qwen_nvfp4@qwen36` after local rebuild |
| remove all local cache | `flashcli bundle clean "$BUNDLE@qwen3" --full`; everything: `flashcli bundle clean --full` |
