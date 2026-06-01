# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

One **SM120 NVFP4** multi-env runtime zip; catalog presets select weights via `bundle_variant`.

## Layout

Native modules under **`lib/`** (matrix: `sm120` × **cu130** × `py310|311|312`). NVFP4 lives inside `flash_rt_kernels`. Weights are **not** in the zip — pulled from Hugging Face per preset.

| variant | weights | MTP (qwen36 only) |
|---------|---------|-------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) |

Do **not** place `flash_rt_*.so` at the bundle root — only under `lib/`.

## Release build (maintainers)

Requires **Linux + Docker + GPU** (default image `nvcr.io/nvidia/pytorch:25.10-py3`) or `--native` with CUDA 13 toolkit on host.

**There is no cu124 line** — nvcc 12.4 cannot compile sm_120 / sm_120a.

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
# equivalent: cd bundles/qwen_nvfp4 && bash release.sh --clean
```

Background + log:

```bash
bash scripts/run_bg.sh --name release-qwen -- \
  bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

Pre-check (no compile): `bash scripts/build_release_matrix.sh --bundle qwen_nvfp4 --check-only`

Artifact example:

```text
bundles/qwen_nvfp4/dist/flashcli-bundle-qwen_nvfp4-{abi}-sm120-multi-linux-x86_64-{timestamp}.zip
```

Upload to CDN; update **both** Qwen presets in `models.yaml` with the same `bundle.zip` URL.

See [README.zh-CN.md](README.zh-CN.md) and [docs/runtime-matrix.md](../../docs/runtime-matrix.md#qwen_nvfp4-sm120--cu130).

## Run

```bash
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000 --max-seq 2048 --max-q-seq 1024 --warmup-preset auto
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 4
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 4 --max-seq 262208 --warmup-preset agent
```

Local bundle (no CDN):

```bash
flashcli run qwen3-8b-nvfp4 --bundle "$(pwd)/bundles/qwen_nvfp4" --prompt "Hello"
```
