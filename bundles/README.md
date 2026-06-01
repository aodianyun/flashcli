# Model Bundles

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Reference implementations and release sources for flashcli Model Bundles. End users install runtimes via `models.yaml` → `bundle.zip`, not from this tree directly.

## Published

| Directory | Presets | Runtime matrix |
|-----------|---------|----------------|
| [`pi05_libero/`](pi05_libero/) | `pi05_libero` | SM89 × cu124/cu130 × py310/311/312 |
| [`qwen_nvfp4/`](qwen_nvfp4/) | `qwen3-8b-nvfp4`, `qwen36-27b-nvfp4` | SM120 × **cu130 only** × py310/311/312; one zip, `bundle_variant` selects weights |

## Maintainer release

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean   # or qwen_nvfp4
# equivalent: cd bundles/<name> && bash release.sh --clean
```

Artifacts: `bundles/<name>/dist/flashcli-bundle-*-sm*-multi-linux-x86_64-*.zip` → upload CDN → update [`models.yaml`](../src/flashcli/catalog/models.yaml).

Hook contract: [`scripts/lib/bundle_hooks.sh`](../scripts/lib/bundle_hooks.sh). Full pipeline: [docs/runtime-matrix.md](../docs/runtime-matrix.md).

## Adding a new bundle

Copy layout from `pi05_libero` or `qwen_nvfp4`, then follow [docs/model_bundle_standard.md](../docs/model_bundle_standard.md) and [CONTRIBUTING.md](../CONTRIBUTING.md).
