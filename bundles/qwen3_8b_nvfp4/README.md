# Qwen3-8B NVFP4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Qwen3-8B chat model in FlashRT NVFP4 on NVIDIA Blackwell (SM120).

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen3_8b_nvfp4:1.0.0` |
| **Weights** | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run`, `serve` |

**Input:** chat prompt (`--prompt`).
**Output:** generated text (OpenAI-compatible chat completion; `serve` supports SSE streaming).

Weights are pulled on first `pull` / `run` / `serve` and cached in the v4 weights store; they are not in the bundle.

## Run

```bash
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --prompt "Hello" --max-tokens 128
```

## Serve

```bash
flashcli serve flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --host 0.0.0.0 --port 8000
```

Full flags: `flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --help` · `flashcli serve flashcli-bundle/qwen3_8b_nvfp4:1.0.0 --help`

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

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | Torch device for inference. |
| `--max-seq` | `2048` | KV / context length budget. |
| `--max-q-seq` | `128` | Max prefill chunk size. |
| `--model-name` | `qwen3` | OpenAI API model id exposed by serve. |
| `--warmup-preset` | `auto` | Warmup bucket preset: auto|short|all|none. |
| `--warmup` | `32:128,128:256` | Extra CUDA graph warmup shapes (batch:seq,...). |

Build/release: [BUILD.md](BUILD.md).
