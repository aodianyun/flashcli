# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Reference bundle sources. End users install via FlashHub (`models.yaml` → `bundle.repo`).

## Build and release (maintainers)

**Full step-by-step guide** → **[docs/bundle_builder_guide.md](../docs/bundle_builder_guide.md)**

```bash
cd flashcli
pip install -e ./flashcli-bundle -e .
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # or qwen_nvfp4
```

## Published bundles

| Directory | Presets | Runtime matrix |
|-----------|---------|----------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | SM89 × cu124/cu130 × py312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`, `qwen36-27b-nvfp4` | SM120 × cu130 × py312 |

Spec: **[bundle_publish_standard.md](../docs/bundle_publish_standard.md)** · summary [model_bundle_standard.md](../docs/model_bundle_standard.md)
