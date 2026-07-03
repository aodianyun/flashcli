# Qwen NVFP4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

基于 **FlashRT** 的 NVFP4 对话模型，面向 NVIDIA **Blackwell（SM120）**。同一 FlashHub repo，ref 中 `@variant` 选择权重。

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` 或 `@qwen36` |
| **GPU** | NVIDIA **SM120** · CUDA **13.x** |
| **Python** | **3.12**（bundle venv） |
| **能力** | `run`、`serve`（OpenAI 兼容 HTTP） |

| Variant | 权重 | 说明 |
|---------|------|------|
| `@qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | 8B 对话 |
| `@qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | 27B + MTP 投机解码 |

`@qwen36` 另需 [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) 中的 `mtp.safetensors`。

## 运行

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 \
  --prompt "你好" --max-tokens 128

flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 \
  --prompt "你好" --max-tokens 128 --K 6
```

## 服务

单卡同时只跑一个 `flashcli serve`。切换 variant 前先停掉上一个进程。

```bash
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 \
  --host 0.0.0.0 --port 8000

flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 \
  --host 0.0.0.0 --port 8000 --K 6
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen36","messages":[{"role":"user","content":"你好"}],"max_tokens":128,"stream":true}'
```

完整参数：`flashcli run … --help` · `flashcli serve … --help`

## 参数

### `run`（两 variant 共用）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `Hello!` | 用户消息 |
| `--max-tokens` | `256` | 最大生成 token 数 |
| `--temperature` | `0.0` | 采样温度 |
| `--top-p` | `1.0` | Nucleus 采样 |
| `--top-k` | `0` | Top-k（`0` 关闭） |
| `--seed` | — | 随机种子（可选） |
| `--K` | `4` | MTP 投机 K（**仅 qwen36**） |

### `serve` — `@qwen3`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--max-seq` | `2048` | 上下文长度 |
| `--max-q-seq` | `128` | 最大 prefill 块 |
| `--model-name` | `qwen3` | OpenAI `model` 字段 |
| `--warmup-preset` | `auto` | 图预热 |

### `serve` — `@qwen36`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--max-seq` | `262208` | 长上下文预算 |
| `--K` | `4` | MTP 投机 K |
| `--default-max-tokens` | `2048` | 客户端未传 `max_tokens` 时默认 |
| `--max-output-tokens` | `16384` | 单次请求硬上限 |
| `--model-name` | `qwen36` | OpenAI `model` 字段 |
| `--warmup-preset` | `agent` | 图预热 |
