# flashcli documentation

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

## By role

### End users

Install and run presets — [../README.md](../README.md), then [QUICKSTART](../bundles/pi05_libero/QUICKSTART.md) per model. Mirrors and cache paths: [environment.md](environment.md).

### Catalog integrators

Pin presets and FlashHub URLs — inline ref strings; see [model_bundle_standard.md](model_bundle_standard.md).

### External bundle authors

Publish a bundle to FlashHub — [bundle_publish_standard.md](bundle_publish_standard.md) + [flashcli-bundle/README.md](../flashcli-bundle/README.md).

### Architecture (optional)

Host CLI vs bundle venv, sync flow, module map — [architecture.md](architecture.md).

## Doc index

| Doc | Purpose |
|-----|---------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | Manifest, entry, `.so`, FlashHub layout (authoritative spec) |
| [model_bundle_standard.md](model_bundle_standard.md) | Preset ref syntax + end-user runtime flow |
| [architecture.md](architecture.md) | Host CLI, bundle venv, re-exec, module map |
| [environment.md](environment.md) | Environment variables |

Per-preset commands: [bundles/](../bundles/)
