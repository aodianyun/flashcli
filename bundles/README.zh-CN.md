# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

flashcli Model Bundle 的参考实现与发布源码。终端用户通过 `models.yaml` → `bundle.zip` 安装 runtime，而非直接使用本目录。

## 对外发布

| 目录 | Preset | Runtime 矩阵 |
|------|--------|----------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | SM89 × cu124/cu130 × py310/311/312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`、`qwen36-27b-nvfp4` | SM120 × **仅 cu130** × py310/311/312；一个 zip，`bundle_variant` 选权重 |

## 维护者发布

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # 或 qwen_nvfp4
# 等价：cd bundles/<name> && bash release.sh --clean
```

产物：`bundles/<name>/dist/flashcli-bundle-*-sm*-multi-linux-x86_64-*.zip` → 上传 CDN → 更新 [`models.yaml`](../src/flashcli/catalog/models.yaml)。

Hook 契约：[`scripts/lib/bundle_hooks.sh`](../scripts/lib/bundle_hooks.sh)。完整流程：[docs/runtime-matrix.zh-CN.md](../docs/runtime-matrix.zh-CN.md)。

## 新增 bundle

复制 `pi05_libero` 或 `qwen_nvfp4` 的目录结构，并遵循 [docs/model_bundle_standard.zh-CN.md](../docs/model_bundle_standard.zh-CN.md) 与 [CONTRIBUTING.md](../CONTRIBUTING.md)。
