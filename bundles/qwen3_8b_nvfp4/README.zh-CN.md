# Qwen3-8B NVFP4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

Qwen3-8B NVFP4 是面向 NVIDIA Blackwell（SM120）的 FlashRT NVFP4 对话模型。

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen3_8b_nvfp4:1.0.0` |
| **权重** | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **能力** | `run`, `serve` |

**输入：** 对话 prompt（`--prompt`）。
**输出：** 生成文本（OpenAI 兼容 chat completion；`serve` 支持 SSE 流式）。

权重在首次 `pull` / `run` / `serve` 时下载并缓存在 v4 weights store，不包含在 bundle 中。

## 运行

```bash
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --prompt "Hello" --max-tokens 128
```

## 服务

```bash
flashcli serve flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --host 0.0.0.0 --port 8000
```

完整参数：`flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --help` · `flashcli serve flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --help`

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

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | Torch device for inference. |
| `--max-seq` | `2048` | KV / context length budget. |
| `--max-q-seq` | `128` | Max prefill chunk size. |
| `--model-name` | `qwen3` | OpenAI API model id exposed by serve. |
| `--warmup-preset` | `auto` | Warmup bucket preset: auto|short|all|none. |
| `--warmup` | `32:128,128:256` | Extra CUDA graph warmup shapes (batch:seq,...). |

构建/发布：[BUILD.zh-CN.md](BUILD.zh-CN.md)。
