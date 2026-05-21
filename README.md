# flashcli

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Distribution CLI** for [FlashRT](https://github.com/flashrt-ai/FlashRT): one command to fetch a Model Bundle, install runtime dependencies, download weights, and run inference.

## Requirements

- **Linux** + **NVIDIA GPU** (verified on **SM89**, e.g. RTX 4090 / L40; bundle metadata also lists SM120)
- **Python** 3.10–3.12
- Network: first run pulls a runtime zip from CDN and model weights from Hugging Face; Pi0.5 also needs Google Storage (PaliGemma tokenizer)

## Quick start

```bash
pip install git+https://github.com/aodianyun/flashcli

flashcli doctor
flashcli models list

flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

On first `run`, flashcli automatically: installs CLI deps → downloads and unpacks the **runtime bundle** (zip) → installs torch etc. per `runtime/manifest.json` → downloads HF weights → `post_pull` (PaliGemma tokenizer) → loads `partner.run.RunEngine` for inference.

Pre-fetch weights (optional):

```bash
flashcli pull pi05_libero
```

Debug a locally assembled bundle:

```bash
flashcli run pi05_libero \
  --bundle /path/to/bundle \
  --checkpoint /path/to/ckpt \
  --image /path/to/base.jpg
```

## Current catalog

| Preset | Capability | Runtime source | Weights |
|--------|------------|----------------|---------|
| `pi05_libero` | `run` | CDN zip (`models.yaml` → `bundle.zip`) | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) |

`models.yaml` only registers **preset names** and **bundle sources**; `weights`, `entry`, `defaults`, etc. live in each bundle’s [`flashcli-bundle.json`](docs/model_bundle_standard.md).

## Local cache

| Path | Contents |
|------|----------|
| `~/.flashcli/bundles/<preset>/` | Unpacked runtime zip |
| `~/.flashcli/models/<preset>/checkpoint/` | Hugging Face weights |
| `~/.cache/flash_rt/` | PaliGemma tokenizer (`post_pull`) |

## Environment variables

| Variable | Description |
|----------|-------------|
| `FLASHCLI_HOME` | Cache root (default `~/.flashcli`) |
| `FLASHCLI_SKIP_AUTO_INSTALL=1` | Skip automatic pip install of manifest deps |
| `FLASH_RT_PALIGEMMA_TOKENIZER` | Path to PaliGemma tokenizer file |

## Commands

| Command | Description |
|---------|-------------|
| `flashcli run <preset>` | Batch inference for VLA etc. (`pi05_libero` uses this) |
| `flashcli pull <preset>` | Pre-fetch weights only |
| `flashcli models list` | Show catalog |
| `flashcli doctor` | Environment and GPU check |
| `flashcli bundle validate PATH` | Validate local bundle layout |
| `--bundle PATH` | Override catalog with local bundle root |

`flashcli serve` is for LLM bundles with HTTP; **`pi05_libero` supports `run` only**.

`flash` and `flashcli` are the same entry point (both registered in `pyproject.toml`).

## Documentation

Full index (with 简体中文): [docs/README.md](docs/README.md)

| Doc | Audience |
|-----|------------|
| [docs/model_bundle_standard.md](docs/model_bundle_standard.md) | Model Bundle format (extend / maintain) |
| [docs/architecture.md](docs/architecture.md) | Modules and data flow |

For inference kernels and precision details, see the [FlashRT](https://github.com/flashrt-ai/FlashRT) repository.

## License

Apache-2.0 (see `pyproject.toml`).
