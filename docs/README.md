# flashcli documentation

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

## By role

- **End users** — install and run presets: [../README.md](../README.md), then each bundle [README](../bundles/README.md). Mirrors and cache paths: [environment.md](environment.md).
- **Integrators** — pin preset refs from [FlashHub](https://flashhub.top): [model_bundle_standard.md](model_bundle_standard.md).
- **External bundle authors** — publish to FlashHub: [bundle_publish_standard.md](bundle_publish_standard.md) (+ [flashcli-bundle/README.md](../flashcli-bundle/README.md)); execution backends: [bundle_execution_abi.md](bundle_execution_abi.md).
- **Maintainers** — build/release bundles: [bundle_builder_guide.md](bundle_builder_guide.md) · [runtime-matrix.md](runtime-matrix.md).
- **Contributors / architecture** — [architecture.md](architecture.md), [module_layers.md](module_layers.md); rules: [../CONTRIBUTING.md](../CONTRIBUTING.md).

## Doc index

| Doc | Audience | Purpose |
|-----|----------|---------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | external authors | **Authoritative** manifest, entry, `.so`, FlashHub layout |
| [bundle_execution_abi.md](bundle_execution_abi.md) | external authors | `entry.kind` backends, native process / `.so` contracts, conformance |
| [model_bundle_standard.md](model_bundle_standard.md) | integrators | Preset ref syntax + end-user runtime flow |
| [environment.md](environment.md) | users | Environment variables, mirrors, cache paths |
| [architecture.md](architecture.md) | contributors | Runtime flow, core principles, host vs bundle |
| [module_layers.md](module_layers.md) | contributors | Host / infer / protocol package boundaries |
| [bundle_builder_guide.md](bundle_builder_guide.md) | maintainers | Build, matrix release, FlashHub upload |
| [runtime-matrix.md](runtime-matrix.md) | maintainers | SM × CUDA × Python release matrix |

Per-bundle commands and build docs: [`bundles/`](../bundles/README.md).
