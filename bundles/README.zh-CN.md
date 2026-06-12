# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

flashcli Model Bundle 参考实现与发布源码。终端用户通过 FlashHub（`models.yaml` → `bundle.repo`）安装，不直接使用本目录。

## 构建与发布（维护者）

**完整逐步说明** → **[docs/bundle_builder_guide.zh-CN.md](../docs/bundle_builder_guide.zh-CN.md)**  
（环境镜像、本地 build、release 流水线、FlashHub 上传、catalog 更新）

```bash
cd flashcli
pip install -e ./flashcli-bundle -e .
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # 或 qwen_nvfp4
```

## 已发布 bundle

| 目录 | Preset | Runtime 矩阵 |
|------|--------|----------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | SM89 × cu124/cu130 × py312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`、`qwen36-27b-nvfp4` | SM120 × cu130 × py312 |

格式规范：**对外发布标准** [bundle_publish_standard.zh-CN.md](../docs/bundle_publish_standard.zh-CN.md) · 摘要 [model_bundle_standard.zh-CN.md](../docs/model_bundle_standard.zh-CN.md)
