# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

## 对外发布

| 目录 | Preset | 状态 |
|------|--------|------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | **已发布** — runtime 通过 `models.yaml` 的 `bundle.zip` 分发；权重从 Hugging Face 拉取 |

用户安装 `flashcli` 后**不需要**本目录；仅维护者从源码打 zip 时需要 `pi05_libero/`。

## 仓库内草稿（未发布）

以下目录供 monorepo 内开发，**未写入 `models.yaml`**，runtime **未做对外验证**，请勿当作产品文档中的可用 preset：

- [`qwen_nvfp4/`](qwen_nvfp4/) — **Qwen3 + Qwen3.6 NVFP4**（单 runtime；catalog preset + `bundle_variant`，需 SM120）

新包请从 [`_template/`](_template/) 拷贝，并阅读 [docs/model_bundle_standard.zh-CN.md](../docs/model_bundle_standard.zh-CN.md)。
