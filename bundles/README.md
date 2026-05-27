# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

## Published

| Directory | Preset | Status |
|-----------|--------|--------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | **Released** — runtime via `models.yaml` `bundle.zip`; weights from Hugging Face |

End users who `pip install flashcli` **do not need** this directory; maintainers use `pi05_libero/` to build release zips from source.

## In-repo drafts (unpublished)

These directories are for monorepo development. They are **not** in `models.yaml` and runtimes are **not** validated for public use. Do not document them as available presets:

- [`qwen_nvfp4/`](qwen_nvfp4/) — **Qwen3 + Qwen3.6 NVFP4** (one runtime; catalog presets + `bundle_variant`, SM120)

For a new bundle, copy [`_template/`](_template/) and read [docs/model_bundle_standard.md](../docs/model_bundle_standard.md).
