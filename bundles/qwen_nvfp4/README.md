# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

One **SM120 NVFP4** FlashHub repo; `@qwen3` / `@qwen36` in the ref selects weights.

## Layout

`format_version: 3` manifest with `runtime: { env_key: path }`. Native `.so` live under `runtime/<env-key>/` on FlashHub and after sync; flashcli loads them in place. Requires **SM120 × cu130 × Python 3.12** (bundle venv). Weights are **not** in the bundle — pulled from Hugging Face per variant.

| variant | weights | MTP (qwen36 only) |
|---------|---------|-------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) |

## Run

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --prompt "Hello"
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --host 0.0.0.0 --port 8000 --max-seq 2048 --max-q-seq 1024 --warmup-preset auto
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --prompt "Hi" --K 4
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --port 8000 --K 6 --max-seq 262208 --warmup-preset auto
```

Local bundle (no FlashHub):

```bash
flashcli run bundles/qwen_nvfp4@qwen3 --prompt "Hello"
```
