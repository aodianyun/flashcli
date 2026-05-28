# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

## Published

| Directory | Presets | Notes |
|-----------|---------|-------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | Multi-env zip: SM89 × cu124/cu130 × py310/311/312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`, `qwen36-27b-nvfp4` | One zip; `bundle_variant` selects weights; SM120 × cu130 |

End users get runtimes via `models.yaml` `bundle.zip` — not from this source tree.

## Other

- [`_template/`](_template/) — starting point for new bundles

See [docs/model_bundle_standard.md](../docs/model_bundle_standard.md).
