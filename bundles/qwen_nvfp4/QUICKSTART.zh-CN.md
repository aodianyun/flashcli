# qwen_nvfp4 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA **SM120** · CUDA **13.x** · Python **3.12**（bundle venv；主机 CLI 3.10+）  
**Ref**：`flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` / `@qwen36`（同一 FlashHub repo，`@variant` 区分权重）

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"   # 本地 dev；省略则走 FlashHub sync
```

---

## 1. 本地 bundle 编译（dev 必做）

FlashHub sync 后 `.so` 在 `runtime/<env-key>/`。本地 `build.sh` 先产出到 `lib/`，需 staging 到对应 runtime 目录再 validate/run：

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen_nvfp4/${ENV_KEY}"
cp bundles/qwen_nvfp4/lib/*.so "bundles/qwen_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

缺 `runtime/<env-key>/flash_rt_kernels*.so` 时 serve 会报 `ImportError: flash_rt_kernels`。

---

## 2. 拉权重

```bash
flashcli pull "$BUNDLE@qwen3"
flashcli pull "$BUNDLE@qwen36"
# ~/.flashcli/models/qwen_nvfp4/1.0.1@qwen3/checkpoint/
# qwen36 MTP: ~/.flashcli/models/qwen_nvfp4/1.0.1@qwen36/mtp_fp8/
```

内网：`export HF_ENDPOINT=https://hf-mirror.com`

---

## 3. 引擎层（无 HTTP）

```bash
flashcli run "$BUNDLE@qwen3" --help
flashcli run "$BUNDLE@qwen36" --help

flashcli run "$BUNDLE@qwen3" --prompt "Hello" --max-tokens 64

flashcli run "$BUNDLE@qwen36" --prompt "Hello" --max-tokens 64 --K 6
```

---

## 4. HTTP serve

**同一 GPU 同时只跑一个 serve。** qwen3 与 qwen36 需分别起停。

```bash
flashcli serve "$BUNDLE@qwen3" --help
flashcli serve "$BUNDLE@qwen36" --help

flashcli serve "$BUNDLE@qwen3" --host 0.0.0.0 --port 8000

flashcli serve "$BUNDLE@qwen36" --host 0.0.0.0 --port 8000 --K 6
```

| 参数 | qwen3 默认 | qwen36 默认 | 说明 |
|------|------------|-------------|------|
| `--max-seq` | 2048 | 262208 | prompt + 生成总上下文 |
| `--max-output-tokens` | — | **16384** | 单次请求生成硬上限（qwen36 serve） |
| `--default-max-tokens` | — | 2048 | 客户端未传 `max_tokens` 时（qwen36） |
| `--K` | — | 4 | MTP 投机步数；bench 常用 6 |

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
    "model": "qwen36",
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
# 权重缓存在 ~/.flashcli/models/qwen_nvfp4/1.0.1@<variant>/；可用 flashcli models show "$BUNDLE@qwen3" 查看路径
export CKPT_QWEN3=~/.flashcli/models/qwen_nvfp4/1.0.1@qwen3/checkpoint
export CKPT_QWEN36=~/.flashcli/models/qwen_nvfp4/1.0.1@qwen36/checkpoint

bash scripts/bench_qwen_curl.sh --qwen3-only --rounds 5

QWEN36_MAX_SEQ=262208 QWEN36_PORT=8000 \
  bash scripts/bench_qwen_curl.sh --qwen36-only \
  --profile comparable --qwen36-long-tokens 262144 \
  --rounds 12 --skip-first 2
```

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| `ImportError: flash_rt_kernels` | 未编译或未 staging；确认 `runtime/<env-key>/` 含本机 SM/CUDA/Python 的 `.so` |
| `max_tokens must be <= N` | 提高 `--max-output-tokens`，或减小请求里的 `max_tokens` |
| 首次请求很慢 | 新 `(prompt_len, max_tokens)` 触发 CUDA Graph capture；第二次通常快很多 |
| FlashHub runtime 过旧 | 本地 rebuild 后用 `flashcli run bundles/qwen_nvfp4@qwen36`（或 `$BUNDLE@qwen36`） |
| 完全删除本机缓存 | `flashcli bundle clean "$BUNDLE@qwen3" --full`；全部：`flashcli bundle clean --full` |
