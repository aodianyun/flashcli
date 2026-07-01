# qwen3_vl_nvfp4 quick start

<p align="right"><a href="QUICKSTART.zh-CN.md">简体中文</a></p>

**Requires**: Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.12** (bundle venv; host CLI 3.10+)  
**Ref**: `flashcli-bundle/qwen3_vl_nvfp4:1.0.0`

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4"   # local dev; omit for FlashHub sync
```

---

## 1. Build local bundle (dev)

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen3_vl_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen3_vl_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen3_vl_nvfp4/${ENV_KEY}"
cp bundles/qwen3_vl_nvfp4/lib/*.so "bundles/qwen3_vl_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

Missing `flash_rt_qwen3_vl_kernels*.so` → vision path fails at load time.

---

## 2. Weights

**Runtime needs FlashRT NVFP4 checkpoint** (not BF16 source weights).

**Maintainer / local quantize:**

```bash
bash bundles/qwen3_vl_nvfp4/scripts/prepare_qwen3_vl_weights.sh \
  --flashrt-repo "$FLASHRT_REPO" \
  --dst /tmp/Qwen3-VL-8B-FlashRT-NVFP4

# Dev embed:
bash bundles/qwen3_vl_nvfp4/build.sh --embed-checkpoint /tmp/Qwen3-VL-8B-FlashRT-NVFP4
```

**After HF publish** (update `weights.repo` in manifest):

```bash
flashcli pull "$BUNDLE"
# ~/.flashcli/models/qwen3_vl_nvfp4/1.0.0/checkpoint/
```

Restricted network: `export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. Engine (`run`, no HTTP)

```bash
flashcli run "$BUNDLE" --help

flashcli run "$BUNDLE" \
  --image /path/to/scene.jpg \
  --prompt "Describe this image in one sentence." \
  --max-tokens 128
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--image` | — | **Required** RGB image path |
| `--max-pixels` | 500000 | Cap image resolution (VRAM / TTFT) |
| `--max-tokens` | 256 | Max new tokens |

**16 GB GPU:** add `--max-pixels 500000` and serve `--max-seq 2048`.

---

## 4. HTTP serve

```bash
flashcli serve "$BUNDLE" --host 0.0.0.0 --port 8000 --max-pixels 500000 --warmup-preset short
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--model-name` | `qwen3-vl` | OpenAI `model` id |
| `--max-seq` | 4096 | Context budget |
| `--max-pixels` | 500000 | Image resolution cap |
| `--warmup-preset` | `none` | `short` captures decode graphs with dummy image |

---

## 5. curl smoke tests

**Text + image (stream):**

```bash
IMG_B64="$(python3 -c "import base64; print(base64.b64encode(open('scene.jpg','rb').read()).decode())")"

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"qwen3-vl\",
    \"messages\": [{
      \"role\": \"user\",
      \"content\": [
        {\"type\": \"text\", \"text\": \"What is in this image?\"},
        {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/jpeg;base64,${IMG_B64}\"}}
      ]
    }],
    \"max_tokens\": 128,
    \"temperature\": 0,
    \"stream\": true
  }"
```

**Tools (text-only smoke):**

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-vl",
    "messages": [{"role": "user", "content": "What is the weather in Boston?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
      }
    }],
    "max_tokens": 256,
    "temperature": 0
  }' | jq
```

```bash
curl -s http://127.0.0.1:8000/health | jq
```

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ImportError: flash_rt_kernels` | build bundle; copy `lib/*.so` into `runtime/<env-key>/` |
| `flash_rt_qwen3_vl_kernels is not built` | rebuild with `-DFLASHRT_BUILD_QWEN3_VL=ON` (build.sh does this) |
| missing `w16a16_gemm_sm120_bf16` | rebuild native libs with `-DFLASHRT_ENABLE_QWEN35MOE=ON` (build.sh enables this); repack alone is insufficient |
| OOM on 16 GB | lower `--max-pixels` and `--max-seq` |
| multimodal `image_processor` / processor errors | bundle runtime needs `transformers>=4.57.0` (`Qwen3VLProcessor`); older `<4.56` loads tokenizer-only even when `preprocessor_config.json` exists |
| `transformers 4.55.x does not include Qwen3VLProcessor` | `flashcli bundle install bundles/qwen3_vl_nvfp4/dist/ --force` or `pip install "transformers>=4.57.0"` in the bundle venv |
| BF16 checkpoint load errors | quantize with `prepare_qwen3_vl_weights.sh`; runtime needs NVFP4 layout |
| slow first request | warmup: `--warmup-preset short` or `--warmup 32` |
