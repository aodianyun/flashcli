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
# pip install --force-reinstall git+https://github.com/aodianyun/flashcli.git

flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

On first `run`, flashcli automatically: installs CLI deps → resolves the bundle source from `models.yaml` for this GPU → downloads and unpacks the **runtime bundle** → installs torch etc. per `flashcli-bundle.json` `python_dependencies` → downloads HF weights → `post_pull` (PaliGemma tokenizer) → loads bundle `entry` (e.g. `run.RunEngine`) for inference.

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
| `pi05_libero` | `run` | CDN zip (`models.yaml` → `bundle.variants`, chosen by GPU) | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) |

`models.yaml` only registers **preset names** and **bundle sources** (single env: top-level `zip`/`path`/`git`; multi env: `bundle.variants.<sm*-cu*-os-arch>`). `weights`, `entry`, `defaults`, etc. live in each bundle’s [`flashcli-bundle.json`](docs/model_bundle_standard.md).

Check which environment matches this machine:

```bash
flashcli models envs pi05_libero
```

## Local cache

| Path | Contents |
|------|----------|
| `~/.flashcli/bundles/<preset>/` | Unpacked runtime zip |
| `~/.flashcli/models/<preset>/checkpoint/` | Hugging Face weights |
| `~/.cache/flash_rt/` | PaliGemma tokenizer (`post_pull`) |

## Environment variables

Common variables (full reference: **[docs/environment.md](docs/environment.md)**):

| Variable | Description |
|----------|-------------|
| `FLASHCLI_HOME` | Cache root (default `~/.flashcli`) |
| `FLASHCLI_BUNDLES_DIR` | Override bundle cache (default `$FLASHCLI_HOME/bundles`) |
| `FLASHCLI_MODELS_DIR` | Override HF weights cache (default `$FLASHCLI_HOME/models`) |
| `FLASHCLI_MODELS_YAML` | Override preset catalog path (default: packaged `flashcli/catalog/models.yaml`) |
| `FLASHCLI_SKIP_AUTO_INSTALL=1` | Skip auto pip install of flashcli CLI deps (same as `--no-auto-install`) |
| `FLASHCLI_SKIP_BUNDLE_ZIP=1` | Do not download `bundle.zip` from catalog |
| `FLASHCLI_SKIP_BUNDLE_GIT=1` | Do not git-fetch bundles |
| `HF_ENDPOINT` | Hugging Face Hub mirror (e.g. `https://hf-mirror.com`); auto-retries mirror if unset and Hub fails |
| `HF_TOKEN` | Hugging Face token for gated models (`huggingface_hub`) |
| `FLASH_RT_PALIGEMMA_TOKENIZER` | Pi0.5 PaliGemma tokenizer file path |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | Qwen3.6 MTP weights dir (or `--mtp-checkpoint`) |

## Commands

| Command | Description |
|---------|-------------|
| `flashcli run <preset>` | Batch inference for VLA etc. (`pi05_libero` uses this) |
| `flashcli pull <preset>` | Pre-fetch weights only |
| `flashcli models list` | Show catalog and cache status |
| `flashcli models envs [preset]` | List `models.yaml` environments and GPU match |
| `flashcli doctor` | Environment and GPU check |
| `flashcli bundle sync <preset>` | Pre-fetch or update runtime bundle |
| `flashcli bundle validate PATH` | Validate local bundle layout |
| `--bundle PATH` | Override catalog with local bundle root |

`flashcli serve` is for LLM bundles with HTTP; **`pi05_libero` supports `run` only**.

`flash` and `flashcli` are the same entry point (both registered in `pyproject.toml`).

## Documentation

Full index (with 简体中文): [docs/README.md](docs/README.md)

| Doc | Audience |
|-----|------------|
| [docs/environment.md](docs/environment.md) | Environment variables |
| [docs/model_bundle_standard.md](docs/model_bundle_standard.md) | Model Bundle format (extend / maintain) |
| [docs/architecture.md](docs/architecture.md) | Modules and data flow |

For inference kernels and precision details, see the [FlashRT](https://github.com/flashrt-ai/FlashRT) repository.

## License

Apache-2.0 (see `pyproject.toml`).
