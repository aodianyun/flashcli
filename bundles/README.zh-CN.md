# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

FlashHub 上的 bundle 参考源码。终端用户通过 catalog 的 `bundle.repo` 安装 — 各 preset 见 [QUICKSTART](pi05_libero/QUICKSTART.zh-CN.md)。

## 已发布 bundle

| 目录 | Preset | GPU / CUDA |
|------|--------|------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | **SM89** · cu124 或 cu130 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`、`qwen36-27b-nvfp4` | **SM120** · 仅 cu130 |

Bundle 规范：[bundle_publish_standard.zh-CN.md](../docs/bundle_publish_standard.zh-CN.md) · catalog 流程：[model_bundle_standard.zh-CN.md](../docs/model_bundle_standard.zh-CN.md)
