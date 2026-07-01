# flashcli documentation

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

## By role

### End users

Install and run presets — [../README.md](../README.md), then [QUICKSTART](../bundles/pi05_libero/QUICKSTART.md) per model. Mirrors and cache paths: [environment.md](environment.md).

### Integrators

Pin preset refs from [FlashHub](https://flashhub.top). Ref syntax: [model_bundle_standard.md](model_bundle_standard.md).

### External bundle authors

Publish a bundle to FlashHub — [bundle_publish_standard.md](bundle_publish_standard.md) + [flashcli-bundle/README.md](../flashcli-bundle/README.md).

### Architecture (optional)

Host CLI vs bundle venv, sync flow, module map — [architecture.md](architecture.md). Maintainer-oriented layer split: [module_layers.md](module_layers.md).

### Maintainers (internal)

Build, pack, and publish bundles — [bundle_builder_guide.md](bundle_builder_guide.md) · runtime matrix [runtime-matrix.md](runtime-matrix.md) (indexed from [CONTRIBUTING.md](../CONTRIBUTING.md) only).

## Doc index

| Doc | Purpose |
|-----|---------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | Manifest, entry, `.so`, FlashHub layout (authoritative spec) |
| [model_bundle_standard.md](model_bundle_standard.md) | Preset ref syntax + end-user runtime flow |
| [architecture.md](architecture.md) | Host CLI, bundle venv, re-exec, module map |
| [environment.md](environment.md) | Environment variables |
| [module_layers.md](module_layers.md) | Host CLI vs `flashcli_bundle` package boundaries |

Per-preset commands: [bundles/](../bundles/)
