# qwen3_vl_nvfp4 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.12**（bundle venv；主机 CLI 3.10+）  
**Ref**：`flashcli-bundle/qwen3_vl_nvfp4:1.0.0`

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle && pip install -e .
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4"   # 本地 dev；省略则走 FlashHub sync
```

---

## 1. 本地 bundle 编译（dev）

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen3_vl_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen3_vl_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen3_vl_nvfp4/${ENV_KEY}"
cp bundles/qwen3_vl_nvfp4/lib/*.so "bundles/qwen3_vl_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

缺少 `flash_rt_qwen3_vl_kernels*.so` 时视觉路径会在加载阶段失败。

---

## 2. 权重

**运行时需要 FlashRT NVFP4 checkpoint**（非 BF16 源权重）。

**维护者 / 本地量化：**

```bash
bash bundles/qwen3_vl_nvfp4/scripts/prepare_qwen3_vl_weights.sh \
  --flashrt-repo "$FLASHRT_REPO" \
  --dst /tmp/Qwen3-VL-8B-FlashRT-NVFP4

# 开发嵌入：
bash bundles/qwen3_vl_nvfp4/build.sh --embed-checkpoint /tmp/Qwen3-VL-8B-FlashRT-NVFP4
```

**HF 发布后**（更新 manifest `weights.repo`）：

```bash
flashcli pull "$BUNDLE"
# ~/.flashcli/models/qwen3_vl_nvfp4/1.0.0/checkpoint/
```

内网：`export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. 引擎层（无 HTTP）

```bash
flashcli run "$BUNDLE" --help

flashcli run "$BUNDLE" \
  --image /path/to/scene.jpg \
  --prompt "用一句话描述这张图" \
  --max-tokens 128
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--image` | — | **必填** RGB 图片路径 |
| `--max-pixels` | 500000 | 限制分辨率（显存 / TTFT） |
| `--max-tokens` | 256 | 最大生成 token 数 |

**16GB 显卡：** 建议 `--max-pixels 500000`，serve 时 `--max-seq 2048`。

---

## 4. HTTP serve

```bash
flashcli serve "$BUNDLE" --host 0.0.0.0 --port 8000 --max-pixels 500000 --warmup-preset short
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--model-name` | `qwen3-vl` | OpenAI `model` 字段 |
| `--max-seq` | 4096 | 上下文长度 |
| `--max-pixels` | 500000 | 图片分辨率上限 |
| `--warmup-preset` | `none` | `short` 用 dummy 图捕获 decode graph |

---

## 5. curl 冒烟

**图文流式：**

```bash
IMG_B64="$(python3 -c "import base64; print(base64.b64encode(open('scene.jpg','rb').read()).decode())")"

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"qwen3-vl\",
    \"messages\": [{
      \"role\": \"user\",
      \"content\": [
        {\"type\": \"text\", \"text\": \"这张图里有什么？\"},
        {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/jpeg;base64,${IMG_B64}\"}}
      ]
    }],
    \"max_tokens\": 128,
    \"temperature\": 0,
    \"stream\": true
  }"
```

**Tools（纯文本 smoke）：**

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-vl",
    "messages": [{"role": "user", "content": "北京天气怎么样？"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "查询天气",
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

## 6. 常见问题

| 现象 | 处理 |
|------|------|
| `ImportError: flash_rt_kernels` | 未编译或未 staging；确认 `runtime/<env-key>/` 含本机 `.so` |
| `flash_rt_qwen3_vl_kernels is not built` | 用 `build.sh` 重建（已带 `-DFLASHRT_BUILD_QWEN3_VL=ON`） |
| 16GB OOM | 降低 `--max-pixels`、`--max-seq` |
| BF16 权重加载失败 | 需 `prepare_qwen3_vl_weights.sh` 量化后的 NVFP4 目录 |
| 首次请求慢 | `--warmup-preset short` 或 `--warmup 32` |
