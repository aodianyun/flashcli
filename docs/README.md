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
| [flashserver.md](flashserver.md) | users | **Start here** for the local service: overview, diagram, quick start, doc index |
| [flashserver-install.md](flashserver-install.md) | users / admins | Install, config, ports, disk, lifecycle, uninstall, troubleshooting |
| [flashserver-desktop.md](flashserver-desktop.md) | users | Desktop client features, model lifecycle, startup parameters, LAN access |
| [flashserver-api.md](flashserver-api.md) | integrators | API endpoint index and examples; schema in [openapi.yaml](openapi.yaml) |
| [openapi.yaml](openapi.yaml) | integrators | **Authoritative** HTTP contract (also served at `/openapi.yaml`) |
| [environment.md](environment.md) | users | Environment variables the Go host reads, mirrors, cache paths |
| [model_bundle_standard.md](model_bundle_standard.md) | integrators | Preset ref syntax + end-user runtime flow |
| [bundle_publish_standard.md](bundle_publish_standard.md) | bundle authors | **Authoritative** manifest, entry, `.so`, FlashHub layout |
| [app_manifest_standard.md](app_manifest_standard.md) | app authors / integrators | **Authoritative** FlashHub application manifest (v1): fields, install commands, default bundles |
| [application_install_plan.md](application_install_plan.md) | maintainers | `flashcli app` install flow, state machine, rollback, commands, milestones |
| [bundle_execution_abi.md](bundle_execution_abi.md) | bundle authors | `entry.kind` backends, native process / `.so` contracts, conformance |
| [bundle_serve_protocols.md](bundle_serve_protocols.md) | bundle authors | **Authoritative** OpenAI/Anthropic serve integration: capabilities, `ServeEngine`, endpoint I/O |
| [bundle_asr_standard.md](bundle_asr_standard.md) | bundle authors | ASR category supplement: OpenAI-shaped transcription, capability declarations, diarization, limits |
| [bundle_tts_standard.md](bundle_tts_standard.md) | bundle authors | TTS category supplement: `ServeEngine.speech`, reference-audio extras, audio encoding |
| [bundle_ocr_standard.md](bundle_ocr_standard.md) | bundle authors | OCR category supplement: `ocr_serve`, multi-image/batch, `/v1/ocr*` routes |
| [bundle_audio_separation_standard.md](bundle_audio_separation_standard.md) | bundle authors | Audio-separation supplement: `voice`/`ambience` stems, file/URL/path input, local outputs |
| [bundle_video_erase_standard.md](bundle_video_erase_standard.md) | bundle authors | Video-erase category supplement: `/v1/video/erase*`, jobs, mask-guided inpainting |
| [architecture.md](architecture.md) | contributors | Runtime flow, local service stack, host vs bundle, caches, directory layout |
| [module_layers.md](module_layers.md) | contributors | Host / infer / protocol ownership and the Go package map |
| [plans/flashhub-download-reliability.md](plans/flashhub-download-reliability.md) | contributors | FlashHub Bundle validation, retries, temporary-file cleanup, and limitations |
| [bundle_builder_guide.md](bundle_builder_guide.md) | maintainers | Bundle build, multi-CUDA matrix release, FlashHub upload |
| [runtime-matrix.md](runtime-matrix.md) | maintainers | SM × CUDA × Python release matrix |

Per-bundle commands, options, and build docs: [`bundles/`](../bundles/README.md).
Chinese mirrors use the same names with a `.zh-CN.md` suffix.

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
  the matching category standard ([ASR](bundle_asr_standard.md),
  [TTS](bundle_tts_standard.md), [OCR](bundle_ocr_standard.md),
  [audio separation](bundle_audio_separation_standard.md),
  [video erase](bundle_video_erase_standard.md)) when applicable →
  [bundle_builder_guide.md](bundle_builder_guide.md).
- **Maintainer / contributor** — [architecture.md](architecture.md) →
  [module_layers.md](module_layers.md) →
  [FlashHub download reliability](plans/flashhub-download-reliability.md) →
  [../CONTRIBUTING.md](../CONTRIBUTING.md).
