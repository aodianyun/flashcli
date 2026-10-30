# Qwen3.6-27B NVFP4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Qwen3.6-27B chat model with MTP speculative decoding in FlashRT NVFP4 on NVIDIA Blackwell (SM120).

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen36_27b_nvfp4:1.0.0` |
| **Weights** | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) MTP |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run`, `serve` |

**Input:** chat prompt (`--prompt`).
**Output:** generated text (OpenAI-compatible chat completion; `serve` supports SSE streaming).

Weights are pulled on first `pull` / `run` / `serve` and cached in the v4 weights store; they are not in the bundle.

## Run

```bash
flashcli run flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --prompt "Hello" --max-tokens 128 --K 6
```

## Serve

```bash
flashcli serve flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --host 0.0.0.0 --port 8000 --K 6
```

Full flags: `flashcli run flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --help` · `flashcli serve flashcli-bundle/qwen36_27b_nvfp4:1.0.0 --help`

## Parameters

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

Build/release: [BUILD.md](BUILD.md).
