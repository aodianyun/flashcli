# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

> **Internal draft.** One SM120 runtime artifact; multiple catalog presets select weights via `bundle_variant`.

## Pattern

One `bundle.zip` (or `bundle.path`) + `variants` in `flashcli-bundle.json` + multiple `models.yaml` presets sharing that bundle. See [README.zh-CN.md](README.zh-CN.md).

### Hugging Face weights (verified public)

| variant | main weights | MTP (qwen36 only) |
|---------|--------------|-------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | `mtp.safetensors` from [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) |

`JunHowie/Qwen3-8B-Instruct-2512-SFT-NVFP4` is no longer available on Hugging Face.

## Layout

Native modules must live under **`lib/`** (same as `pi05_libero`). See [README.zh-CN.md](README.zh-CN.md).

## Build & run

```bash
flashcli bundle build bundles/qwen_nvfp4 --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli bundle validate bundles/qwen_nvfp4
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 6
```
