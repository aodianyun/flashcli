# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

One **SM120 NVFP4** FlashHub repo; catalog presets select weights via `bundle_variant`.

## Layout

`format_version: 3` manifest with `runtime: { env_key: path }`. Native `.so` under `runtime/<env-key>/` on publish; after sync, installed to `lib/`. Matrix: **sm120 × cu130 × py312**. Weights are **not** in the bundle — pulled from Hugging Face per preset.

| variant | weights | MTP (qwen36 only) |
|---------|---------|-------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) |

## Release build (maintainers)

Full step-by-step guide: **[docs/bundle_builder_guide.md](../../docs/bundle_builder_guide.md)**.

Requires **Linux + Docker + GPU** (default `nvcr.io/nvidia/pytorch:25.10-py3`) or `--native` with CUDA 13. Matrix: **sm120 × cu130 × py312**.

```bash
cd flashcli
pip install -e ./flashcli-bundle -e .
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

Upload `dist/` to FlashHub; update **both** Qwen presets in `models.yaml` with the same `bundle.repo` URL.

## Run

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000 --max-seq 2048 --max-q-seq 1024 --warmup-preset auto
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 4
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 6 --max-seq 262208 --warmup-preset auto
```

Local bundle (no FlashHub):

```bash
flashcli run qwen3-8b-nvfp4 --bundle "$(pwd)/bundles/qwen_nvfp4" --prompt "Hello"
```
