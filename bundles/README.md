# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Reference implementations and release sources for flashcli Model Bundles. End users install runtimes via `models.yaml` → `bundle.repo` (FlashHub), not from this tree directly.

## Published bundles

| Directory | Presets | Runtime matrix |
|-----------|---------|----------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | SM89 × cu124/cu130 × py312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`, `qwen36-27b-nvfp4` | SM120 × **cu130 only** × py312; one repo, `bundle_variant` for weights |

## Maintainer release

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # or qwen_nvfp4
```

Artifacts: `bundles/<name>/dist/` (source tree + `runtime/<env-key>/`) → upload to FlashHub → update `bundle.repo` in [`models.yaml`](../src/flashcli/catalog/models.yaml).

Hook contract: [`scripts/lib/bundle_hooks.sh`](../scripts/lib/bundle_hooks.sh). Full pipeline: [docs/runtime-matrix.md](../docs/runtime-matrix.md).

## Adding a bundle

Copy layout from `pi05_libero` or `qwen_nvfp4`; follow [docs/model_bundle_standard.md](../docs/model_bundle_standard.md) and [CONTRIBUTING.md](../CONTRIBUTING.md).
