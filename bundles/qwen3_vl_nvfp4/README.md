# Qwen3-VL NVFP4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Qwen3-VL-8B** multimodal model in FlashRT NVFP4 layout. Image + text chat via `run` or OpenAI-compatible `serve` with SSE streaming and tool calls.

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen3_vl_nvfp4:1.0.0` |
| **Weights** | [cpadyun/Qwen3-VL-8B-FlashRT-NVFP4](https://huggingface.co/cpadyun/Qwen3-VL-8B-FlashRT-NVFP4) (FlashRT NVFP4 checkpoint) |
| **Processor** | [Qwen/Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) |
| **GPU** | NVIDIA **SM120** · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run`, `serve` |

**Supports:** `image` / `image_url`, streaming SSE, sampling, tools / `tool_calls`  
**Not supported (v1):** thinking / `reasoning_content`, video

## Run

```bash
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg \
  --prompt "Describe this image in one sentence." \
  --max-tokens 128
```

## Serve

```bash
flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --host 0.0.0.0 --port 8000 \
  --max-pixels 500000
```

Full flags: `flashcli run … --help` · `flashcli serve … --help`

## Parameters

### `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `Hello!` | User message |
| `--image` | — | Image path, URL, or `data:image/...;base64,...` |
| `--max-tokens` | `256` | Max new tokens |
| `--max-pixels` | `500000` | Cap image resolution (VRAM / TTFT) |
| `--max-seq` | `2048` | Context budget |
| `--max-q-seq` | `1024` | Max prefill (text + vision tokens) |
| `--temperature` | `0.0` | Sampling temperature |
| `--top-p` | `1.0` | Nucleus sampling |
| `--top-k` | `0` | Top-k (`0` = off) |

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--model-name` | `qwen3-vl` | OpenAI `model` id |
| `--max-seq` | `2048` | Context budget |
| `--max-pixels` | `500000` | Image resolution cap |
| `--warmup-preset` | `none` | `short` = decode graph warmup with dummy image |
