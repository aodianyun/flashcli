# flashcli documentation

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

This directory holds the user, integrator, and maintainer docs. Start with the
root [README](../README.md) for install + `run`/`serve`; the table below maps
every file to its audience and content.

## Doc map

| File | Audience | Content |
|------|----------|---------|
| [../README.md](../README.md) | users | Install, `run`/`serve`, news, doc entry points |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | contributors | Layout, dev setup, binaries/desktop build, git workflow, release checklist + notes standard |
| [documentation_standard.md](documentation_standard.md) | contributors | **Authoritative** doc directories, naming, mirrors, index, and review checklist |
| [flashserver.md](flashserver.md) | users | **Start here** for the local service: overview, diagram, quick start, doc index |
| [flashserver-install.md](flashserver-install.md) | users / admins | Install, config, ports, disk, lifecycle, uninstall, troubleshooting |
| [flashserver-desktop.md](flashserver-desktop.md) | users | Desktop client features, model lifecycle, startup parameters, LAN access |
| [flashserver-api.md](flashserver-api.md) | integrators | API endpoint index and examples; schema in [openapi.yaml](openapi.yaml) |
| [openapi.yaml](openapi.yaml) | integrators | **Authoritative** HTTP contract (also served at `/openapi.yaml`) |
| [environment.md](environment.md) | users | Environment variables the Go host reads, mirrors, cache paths |
| [model_bundle_standard.md](model_bundle_standard.md) | integrators | Preset ref syntax + end-user runtime flow |
| [bundle_publish_standard.md](bundle_publish_standard.md) | bundle authors | **Authoritative** manifest, entry, `.so`, FlashHub layout |
| [app_manifest_standard.md](app_manifest_standard.md) | app authors / integrators | **Authoritative** FlashHub application manifest (v1): fields, install commands, default bundles |
| [plans/application_install_plan.md](plans/application_install_plan.md) | maintainers | `flashcli app` install flow, state machine, rollback, commands, milestones |
| [bundle_execution_abi.md](bundle_execution_abi.md) | bundle authors | `entry.kind` backends, native process / `.so` contracts, conformance |
| [bundle_serve_protocols.md](bundle_serve_protocols.md) | bundle authors | **Authoritative** OpenAI/Anthropic serve integration: capabilities, `ServeEngine`, endpoint I/O |
| [flashserver_gateway_scheduler_spec.md](flashserver_gateway_scheduler_spec.md) | contributors / integrators | **Authoritative** flashserver `/v1` OpenAI gateway, `/api/v1` management, preload/unload, scheduler, placement |
| [plans/flashserver_gateway_scheduler_plan.md](plans/flashserver_gateway_scheduler_plan.md) | maintainers | Delivery plan and mandatory compliance rules for the gateway/scheduler |
| [architecture.md](architecture.md) | contributors | Runtime flow, local service stack, host vs bundle, caches, directory layout |
| [module_layers.md](module_layers.md) | contributors | Host / infer / protocol ownership and the Go package map |
| [bundle_builder_guide.md](bundle_builder_guide.md) | maintainers | Bundle build, multi-CUDA matrix release, FlashHub upload |
| [runtime-matrix.md](runtime-matrix.md) | maintainers | SM × CUDA × Python release matrix |

Per-bundle commands, options, and build docs: [`bundles/`](../bundles/README.md).
Delivery plans live in [`plans/`](plans/); Chinese mirrors use the same name plus
`.zh-CN.md`. See [documentation_standard.md](documentation_standard.md).

## Reading paths

- **End user** — root README (install, `run`/`serve`) → the bundle page on
  [FlashHub](https://flashhub.top) (ref, model options) → [environment.md](environment.md)
  for mirrors and cache locations.
- **Local-service user** — root README → [flashserver.md](flashserver.md) →
  [flashserver-install.md](flashserver-install.md) (deployment) /
  [flashserver-desktop.md](flashserver-desktop.md) (client) →
  [flashserver-api.md](flashserver-api.md) + [openapi.yaml](openapi.yaml) when integrating.
- **Integrator** — [model_bundle_standard.md](model_bundle_standard.md) (refs) →
  [openapi.yaml](openapi.yaml) (HTTP) → [environment.md](environment.md).
- **Bundle author** — [bundle_publish_standard.md](bundle_publish_standard.md) →
  [bundle_execution_abi.md](bundle_execution_abi.md) →
  [bundle_serve_protocols.md](bundle_serve_protocols.md) (LLM/audio/image/video serve) →
  [bundle_builder_guide.md](bundle_builder_guide.md).
- **Maintainer / contributor** — [architecture.md](architecture.md) →
  [module_layers.md](module_layers.md) → [../CONTRIBUTING.md](../CONTRIBUTING.md).
