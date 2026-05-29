# Model Bundles

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

## 对外发布

| 目录 | Preset | 状态 |
|------|--------|------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | **已发布** — `bundle.zip`（SM89 × cu124/cu130 × py310/311/312） |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`、`qwen36-27b-nvfp4` | **已发布** — 同一 `bundle.zip`（SM120 × cu124/cu130 × py310/311/312）；权重 HF 拉取 |

## 维护者发布（一键）

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # 或 qwen_nvfp4
# 等价：cd bundles/<name> && bash release.sh --clean
```

产物：`bundles/<name>/dist/flashcli-bundle-*-sm*-multi-linux-x86_64.zip` → 上传 CDN → 更新 `models.yaml`。

Hook 契约见 [`scripts/lib/bundle_hooks.sh`](../scripts/lib/bundle_hooks.sh)。

## 仓库内其他

- [`_template/`](_template/) — 新包起点

新包请阅读 [docs/model_bundle_standard.zh-CN.md](../docs/model_bundle_standard.zh-CN.md) 与对应 bundle 的 `README`。
