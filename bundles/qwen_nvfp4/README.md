# Qwen NVFP4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

NVFP4 chat models on **FlashRT** for NVIDIA **Blackwell (SM120)**. One FlashHub repo; pick weights with `@variant` in the ref.

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` or `@qwen36` |
| **GPU** | NVIDIA **SM120** · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run`, `serve` (OpenAI-compatible HTTP) |

| Variant | Weights | Notes |
|---------|---------|-------|
| `@qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | 8B chat |
| `@qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | 27B + MTP speculative decoding |

`@qwen36` also pulls `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8).

## Run

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 \
  --prompt "Hello" --max-tokens 128

flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 \
  --prompt "Hello" --max-tokens 128 --K 6
```

## Serve

One GPU → one `flashcli serve` process. Stop qwen3 before starting qwen36.

```bash
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 \
  --host 0.0.0.0 --port 8000

flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 \
  --host 0.0.0.0 --port 8000 --K 6
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen36","messages":[{"role":"user","content":"Hello"}],"max_tokens":128,"stream":true}'
```

Full flags: `flashcli run … --help` · `flashcli serve … --help`

## Parameters

### `run` (both variants)

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `Hello!` | User message |
| `--max-tokens` | `256` | Max new tokens |
| `--temperature` | `0.0` | Sampling temperature |
| `--top-p` | `1.0` | Nucleus sampling |
| `--top-k` | `0` | Top-k (`0` = off) |
| `--seed` | — | Random seed (optional) |
| `--K` | `4` | MTP speculative K (**qwen36** only) |

### `serve` — `@qwen3`

| Flag | Default | Description |
|------|---------|-------------|
| `--max-seq` | `2048` | Context budget |
| `--max-q-seq` | `128` | Max prefill chunk |
| `--model-name` | `qwen3` | OpenAI `model` id |
| `--warmup-preset` | `auto` | Graph warmup: `auto` \| `short` \| `all` \| `none` |

### `serve` — `@qwen36`

| Flag | Default | Description |
|------|---------|-------------|
| `--max-seq` | `262208` | Long-context budget |
| `--K` | `4` | MTP speculative K |
| `--default-max-tokens` | `2048` | When client omits `max_tokens` |
| `--max-output-tokens` | `16384` | Hard cap per request |
| `--model-name` | `qwen36` | OpenAI `model` id |
| `--warmup-preset` | `agent` | Graph warmup preset |
