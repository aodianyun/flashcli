# Qwen3.6-27B NVFP4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

Qwen3.6-27B NVFP4 是面向 NVIDIA Blackwell（SM120）的 FlashRT NVFP4 对话模型。

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen36_27b_nvfp4:1.0.0` |
| **权重** | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) MTP |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **能力** | `run`, `serve` |

**输入：** 对话 prompt（`--prompt`）。
**输出：** 生成文本（OpenAI 兼容 chat completion；`serve` 支持 SSE 流式）。

权重在首次 `pull` / `run` / `serve` 时下载并缓存在 v4 weights store，不包含在 bundle 中。

## 运行

```bash
flashcli run flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --prompt "Hello" --max-tokens 128 --K 6
```

## 服务

```bash
flashcli serve flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --host 0.0.0.0 --port 8000 --K 6
```

完整参数：`flashcli run flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --help` · `flashcli serve flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --help`

## 参数

### `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `Hello!` | User message for chat completion. |
| `--max-tokens` | `256` | Maximum new tokens to generate. |
| `--temperature` | `0.0` | Sampling temperature. |
| `--top-p` | `1.0` | Nucleus sampling top-p. |
| `--top-k` | `0` | Top-k sampling (0 disables). |
| `--seed` | — | Random seed (optional). |
| `--K` | `4` | MTP speculative decoding K. |

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | Torch device for inference. |
| `--max-seq` | `262208` | KV / long-context budget. |
| `--K` | `4` | MTP speculative decoding K. |
| `--default-max-tokens` | `2048` | Default max_tokens when the client omits it. |
| `--max-output-tokens` | `16384` | Hard cap on generated tokens per request. |
| `--model-name` | `qwen36` | OpenAI API model id exposed by serve. |
| `--warmup-preset` | `agent` | Warmup bucket preset: agent|short|long|all|none. |
| `--warmup` | `16:128,128:128` | Extra CUDA graph warmup shapes (batch:seq,...). |
| `--warmup-committed-max-prompt` | `1024` | Committed max prompt length for qwen36 graph warmup. |

构建/发布：[BUILD.zh-CN.md](BUILD.zh-CN.md)。
