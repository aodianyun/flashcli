# qwen_nvfp4 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.10–3.12**  
**Preset**：`qwen3-8b-nvfp4` / `qwen36-27b-nvfp4`（共用同一 runtime zip，`bundle_variant` 区分权重）

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"   # 本地 dev；省略则用 CDN zip
```

---

## 1. 本地 bundle 编译（dev 必做）

CDN zip 已含 `lib/*.so`；源码树需先编译：

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
flashcli bundle validate "$BUNDLE"
```

缺 `lib/flash_rt_kernels*.so` 时 serve 会报 `ImportError: flash_rt_kernels`。

---

## 2. 拉权重

```bash
flashcli pull qwen3-8b-nvfp4  --bundle "$BUNDLE"
flashcli pull qwen36-27b-nvfp4 --bundle "$BUNDLE"
# 缓存：~/.flashcli/models/{preset}/checkpoint/
# qwen36 MTP：~/.flashcli/models/qwen36-27b-nvfp4/mtp_fp8/
```

内网：`export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. 引擎层（无 HTTP）

```bash
# qwen3-8B
flashcli run qwen3-8b-nvfp4 --bundle "$BUNDLE" \
  --prompt "你好" --max-tokens 64

# qwen3.6-27B + MTP
flashcli run qwen36-27b-nvfp4 --bundle "$BUNDLE" \
  --prompt "你好" --max-tokens 64 --K 6
```

---

## 4. HTTP serve

**同一 GPU 同时只跑一个 serve。** qwen3 与 qwen36 需分别起停。

### qwen3-8b

```bash
flashcli serve qwen3-8b-nvfp4 --bundle "$BUNDLE" \
  --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 \
  --warmup-preset auto
```

### qwen3.6-27B

```bash
flashcli serve qwen36-27b-nvfp4 --bundle "$BUNDLE" \
  --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 \
  --warmup-preset auto
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--max-seq` | 262208 | prompt + 生成总上下文 |
| `--max-output-tokens` | **16384** | 单次请求生成硬上限 |
| `--default-max-tokens` | 2048 | 客户端未传 `max_tokens` 时 |
| `--K` | 4（bundle） | MTP 投机步数；bench 常用 6 |

**可选 FlashRT 调参**（`flashcli serve` 通常不必设）：

- `FLASHRT_QWEN36_LONG_KV_CACHE` — 长上下文 KV 格式；默认已是 **`fp8`**。仅当要试 TurboQuant 时设 `tq`。
- `FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ` — 原生 FlashRT server 用的长上下文路由阈值。**flashcli 默认 `route_min_seq=0`**，会覆盖该 env，短 prompt 也走 long 路径（日志里 `route=long`）。

---

## 5. curl 冒烟

```bash
# qwen36 短对话（推荐 stream）
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-27b-nvfp4",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 512,
    "temperature": 0,
    "stream": true
  }'

curl -s http://127.0.0.1:8000/health | jq
```

日志：`chat START` / `chat END`；`completion_tokens` 远小于 `max_tokens` 表示 EOS 正常。  
`max_tokens` 超过 `--max-output-tokens` → HTTP 400。

---

## 6. HTTP 性能测试

```bash
export CKPT_QWEN3=~/.flashcli/models/qwen3-8b-nvfp4/checkpoint
export CKPT_QWEN36=~/.flashcli/models/qwen36-27b-nvfp4/checkpoint

# qwen3（serve 在 8000）
bash scripts/bench_qwen_curl.sh --qwen3-only --rounds 5

# qwen36 对标 FlashRT（serve 在 8000，需 --max-seq 262208）
QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 \
  bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 \
  --rounds 12 --skip-first 2
```

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| `ImportError: flash_rt_kernels` | 未编译 bundle 或 `lib/` 与当前 SM/CUDA/Python 不匹配 |
| `max_tokens must be <= N` | 提高 `--max-output-tokens`，或减小请求里的 `max_tokens` |
| 首次请求很慢 | 新 `(prompt_len, max_tokens)` 触发 CUDA Graph capture；第二次通常快很多 |
| CDN zip 行为旧 | 用 `--bundle bundles/qwen_nvfp4` 指向本地 rebuild 产物 |

维护者发布：`bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean` → 更新 `models.yaml` 中两个 preset 的 `bundle.zip`。
