# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Reference bundle **sources** in this repo. Published artifacts live on **[FlashHub](https://flashhub.top)**.

Each bundle has two doc pairs:

| Doc | Audience |
|-----|----------|
| `README.md` / `README.zh-CN.md` | **FlashHub** — model overview, `flashcli run` / `serve` commands and parameters |
| `BUILD.md` / `BUILD.zh-CN.md` | **Maintainers** — compile, pack, validate, smoke test |

## Bundles

| Directory | Ref | GPU / CUDA | Docs |
|-----------|-----|------------|------|
| [`pi05_libero/`](pi05_libero/) | `flashcli-bundle/pi05_libero:1.0.4` | SM89 · cu124/cu130 · SM120 · cu130 | [README](pi05_libero/README.md) · [BUILD](pi05_libero/BUILD.md) |
| [`pi05_libero_nexus/`](pi05_libero_nexus/) | `flashcli-bundle/pi05_libero_nexus:1.0.0` | SM120 · cu130 only | [README](pi05_libero_nexus/README.md) · [BUILD](pi05_libero_nexus/BUILD.md) |
| [`groot_n16/`](groot_n16/) | `flashcli-bundle/groot_n16:1.0.0` | SM120 · cu130 only | [README](groot_n16/README.md) · [BUILD](groot_n16/BUILD.md) |
| [`groot_n17/`](groot_n17/) | `flashcli-bundle/groot_n17:1.0.0` | SM120 · cu130 only | [README](groot_n17/README.md) · [BUILD](groot_n17/BUILD.md) |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3`, `@qwen36` | SM120 · cu130 only | [README](qwen_nvfp4/README.md) · [BUILD](qwen_nvfp4/BUILD.md) |
| [`qwen3_vl_nvfp4/`](qwen3_vl_nvfp4/) | `flashcli-bundle/qwen3_vl_nvfp4:1.0.0` | SM120 · cu130 only | [README](qwen3_vl_nvfp4/README.md) · [BUILD](qwen3_vl_nvfp4/BUILD.md) |

Bundle format: [bundle_publish_standard.md](../docs/bundle_publish_standard.md)
