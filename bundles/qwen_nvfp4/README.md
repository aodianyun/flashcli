# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

One **SM120 NVFP4** multi-env runtime zip; catalog presets select weights via `bundle_variant`.

## Layout

Native modules under **`lib/`** (matrix: `sm120` × `cu130` × `py310|311|312`). Weights are **not** in the zip — pulled from Hugging Face per preset.

| variant | weights | MTP (qwen36 only) |
|---------|---------|-------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) |

## Release build (maintainers)

```bash
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_qwen_release_matrix.sh
flashcli bundle validate bundles/qwen_nvfp4
```

Artifact: `bundles/qwen_nvfp4/dist/flashcli-bundle-qwen_nvfp4-main-sm120-multi-linux-x86_64.zip`

See [README.zh-CN.md](README.zh-CN.md) and [docs/runtime-matrix.md](../../docs/runtime-matrix.md#qwen_nvfp4-sm120--cu130).

## Run

```bash
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli serve qwen3-8b-nvfp4 --port 8000
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 6
```
