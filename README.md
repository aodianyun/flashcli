# flashcli

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Distribution CLI** for [FlashRT](https://github.com/flashrt-ai/FlashRT): one command to fetch a Model Bundle, install runtime dependencies, download weights, and run inference.

## Requirements

- **Linux** + **NVIDIA GPU** (verified on **SM89**, e.g. RTX 4090 / L40; bundle metadata also lists SM120)
- **Python ≥ 3.10** (see [`pyproject.toml`](pyproject.toml)); `install.sh` installs **flashcli** and **`huggingface_hub`** (provides `hf download` / `huggingface-cli download`)
- **Network**: first run pulls a runtime zip from CDN; weights download via Hub CLI. For restricted networks use the **Gitee install script + `--mirror`** below and `export HF_ENDPOINT=https://hf-mirror.com`. Pi0.5 also needs Google Storage (PaliGemma tokenizer)
- **Containers**: use an NVIDIA CUDA runtime image (e.g. `nvcr.io/nvidia/pytorch:24.05-py3`), not plain `python:3.x`; `nvidia-smi` working does not imply `/usr/local/cuda` is present

## Quick start

**Restricted network** (Gitee install script + pip/HF mirrors):

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh

# Restricted network** (Gitee install script + pip/HF mirrors):
# curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror

flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

First `run` fetches the bundle, installs deps, and downloads weights. See [docs/environment.md](docs/environment.md) for install flags and env vars.

## Current catalog

| Preset | Capability | Runtime | Weights |
|--------|------------|---------|---------|
| `pi05_libero` | `run` | CDN zip (SM89 × cu124/cu130 × py310/311/312) | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) |
| `qwen3-8b-nvfp4` | `run`, `serve` | Same CDN zip as qwen36 (SM120 × cu130 × py310/311/312) | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) |
| `qwen36-27b-nvfp4` | `run`, `serve` | Same zip | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + MTP |

`models.yaml` only registers **preset names** and **one bundle source per preset** (`zip`/`path`/`git`). Multi-env native runtimes ship inside that zip’s `lib/` matrix. `weights`, `entry`, `defaults`, etc. live in each bundle’s [`flashcli-bundle.json`](docs/model_bundle_standard.md).

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
| `HF_ENDPOINT` | Hugging Face Hub mirror (e.g. `https://hf-mirror.com`); default tries official Hub first, then mirror on failure |
| `HF_TOKEN` | Hugging Face token for gated models (`huggingface_hub`) |
| `FLASH_RT_PALIGEMMA_TOKENIZER` | Pi0.5 PaliGemma tokenizer file path |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | Qwen3.6 MTP weights dir (or `--mtp-checkpoint`) |

## Commands

| Command | Description |
|---------|-------------|
| `flashcli run <preset>` | Inference (Pi0.5 VLA, Qwen chat, etc.) |
| `flashcli serve <preset>` | OpenAI-compatible HTTP (Qwen NVFP4) |
| `flashcli pull <preset>` | Pre-fetch weights only |
| `flashcli models list` | Show catalog and cache status |
| `flashcli models envs [preset]` | List `models.yaml` environments and GPU match |
| `flashcli doctor` | Environment and GPU check |
| `flashcli bundle sync <preset>` | Pre-fetch or update runtime bundle |
| `flashcli bundle validate PATH` | Validate local bundle layout |
| `--bundle PATH` | Override catalog with local bundle root |

**`pi05_libero` supports `run` only**; Qwen presets support `run` and `serve`.

`flash` and `flashcli` are the same entry point (both registered in `pyproject.toml`).

## Documentation

Full index (with 简体中文): [docs/README.md](docs/README.md)

| Doc | Audience |
|-----|------------|
| [docs/environment.md](docs/environment.md) | Environment variables |
| [docs/model_bundle_standard.md](docs/model_bundle_standard.md) | Model Bundle format (extend / maintain) |
| [docs/architecture.md](docs/architecture.md) | Modules and data flow |

For inference kernels and precision details, see the [FlashRT](https://github.com/LiangSu8899/FlashRT) repository.

## License

Apache-2.0 (see `pyproject.toml`).
