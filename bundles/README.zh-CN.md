# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

本仓库内的 bundle **源码**。已发布制品见 **[FlashHub](https://flashhub.top)**。

每个 bundle 两套文档：

| 文档 | 读者 |
|------|------|
| `README.md` / `README.zh-CN.md` | **FlashHub 对外** — 模型介绍、`flashcli run` / `serve` 命令与参数 |
| `BUILD.md` / `BUILD.zh-CN.md` | **维护者** — 编译、打包、校验、冒烟测试 |

## Bundle 列表

| 目录 | Ref | GPU / CUDA | 文档 |
|------|-----|------------|------|
| [`pi05_libero/`](pi05_libero/) | `flashcli-bundle/pi05_libero:1.0.5` | SM89 · cu124/cu130 · SM120 · cu130 | [README](pi05_libero/README.zh-CN.md) · [BUILD](pi05_libero/BUILD.zh-CN.md) |
| [`groot_n16/`](groot_n16/) | `flashcli-bundle/groot_n16:1.0.1` | SM120 · 仅 cu130 | [README](groot_n16/README.zh-CN.md) · [BUILD](groot_n16/BUILD.zh-CN.md) |
| [`groot_n17/`](groot_n17/) | `flashcli-bundle/groot_n17:1.0.1` | SM120 · 仅 cu130 | [README](groot_n17/README.zh-CN.md) · [BUILD](groot_n17/BUILD.zh-CN.md) |
| [`qwen3_vl_8b_nvfp4/`](qwen3_vl_8b_nvfp4/) | `flashcli-bundle/qwen3_vl_8b_nvfp4:1.0.0` | SM120 · 仅 cu130 | [README](qwen3_vl_8b_nvfp4/README.zh-CN.md) · [BUILD](qwen3_vl_8b_nvfp4/BUILD.zh-CN.md) |
| [`qwen3_8b_nvfp4/`](qwen3_8b_nvfp4/) | `flashcli-bundle/qwen3_8b_nvfp4:1.0.0` | SM120 · 仅 cu130 | [README](qwen3_8b_nvfp4/README.zh-CN.md) · [BUILD](qwen3_8b_nvfp4/BUILD.zh-CN.md) |
| [`qwen36_27b_nvfp4/`](qwen36_27b_nvfp4/) | `flashcli-bundle/qwen36_27b_nvfp4:1.0.0` | SM120 · 仅 cu130 | [README](qwen36_27b_nvfp4/README.zh-CN.md) · [BUILD](qwen36_27b_nvfp4/BUILD.zh-CN.md) |
| [`pi05_libero_nexus/`](pi05_libero_nexus/) | `flashcli-bundle/pi05_libero_nexus:1.0.3` | SM120 · 仅 cu130 | [README](pi05_libero_nexus/README.zh-CN.md) · [BUILD](pi05_libero_nexus/BUILD.zh-CN.md) |
| [`wan22/`](wan22/) | `flashcli-bundle/wan22:1.0.1` | SM120 · 仅 cu130 | [README](wan22/README.zh-CN.md) · [BUILD](wan22/BUILD.zh-CN.md) |
| [`higgs_audio/`](higgs_audio/) | `flashcli-bundle/higgs_audio:1.0.1` | SM120 · 仅 cu130 | [README](higgs_audio/README.zh-CN.md) · [BUILD](higgs_audio/BUILD.zh-CN.md) |

Bundle 文档遵循 [README / BUILD 规范](../docs/bundle_builder_guide.zh-CN.md#101-bundle-readme--build-规范)。

Bundle 格式：[bundle_publish_standard.zh-CN.md](../docs/bundle_publish_standard.zh-CN.md)
