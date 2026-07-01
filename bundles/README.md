# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Reference bundle **sources** in this repo. Published artifacts and the full bundle list live on **[FlashHub](https://flashhub.top)**. End users pin refs such as `flashcli-bundle/pi05_libero:1.0.3` — see [QUICKSTART](pi05_libero/QUICKSTART.md) per bundle.

## Source bundles (examples)

| Directory | Ref(s) | GPU / CUDA |
|-----------|--------|------------|
| [`pi05_libero/`](pi05_libero/) | `flashcli-bundle/pi05_libero:1.0.3` | **SM89** · cu124/cu130 · **SM120** · cu130 |
| [`groot_n16/`](groot_n16/) | *(local dev)* | **SM120** · cu130 only |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3`, `@qwen36` | **SM120** · cu130 only |
| [`qwen3_vl_nvfp4/`](qwen3_vl_nvfp4/) | `flashcli-bundle/qwen3_vl_nvfp4:1.0.0` | **SM120** · cu130 only |

Bundle format: [bundle_publish_standard.md](../docs/bundle_publish_standard.md) · ref syntax: [model_bundle_standard.md](../docs/model_bundle_standard.md)
