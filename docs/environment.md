# Environment variables

<p align="right"><strong>English</strong> · <a href="environment.zh-CN.md">简体中文</a></p>

flashcli uses environment variables for cache locations, the preset catalog, download behavior, and Hugging Face / preset-specific integration. Variables not listed here have **no effect** on flashcli.

Boolean flags: `1`, `true`, or `yes` (case-insensitive) enable the switch.

## Paths and catalog

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_HOME` | `~/.flashcli` | Cache root. Default subdirs: `bundles/`, `models/`, `cache/downloads/`. |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | Override runtime bundle (zip/git) cache. |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | Override Hugging Face weights cache root (per preset usually `<dir>/<preset>/checkpoint/`). |
| `FLASHCLI_MODELS_YAML` | (bundled) | **Override path to the preset catalog file.** Default: `flashcli/catalog/models.yaml` inside the installed package (same for pip wheel and editable installs). File must exist. |

Normally edit [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml) in the repo; set `FLASHCLI_MODELS_YAML` only for multiple catalogs, CI, or mounted configs in containers.

Example:

```bash
export FLASHCLI_HOME=/data/flashcli
export FLASHCLI_MODELS_YAML=/etc/flashcli/models.yaml
flashcli models list
```

## Downloads and Hugging Face

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_ENDPOINT` | (official Hub) | Hugging Face Hub API base URL. Mirror example: `https://hf-mirror.com` ([HF-Mirror](https://hf-mirror.com)). Used by `snapshot_download`. |
| (automatic) | — | If `HF_ENDPOINT` is **not** set, flashcli tries official Hub first, then `https://hf-mirror.com` (via `hf download` / `huggingface-cli download`). |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | When `1`, try mirror before official Hub. |
| `HF_TOKEN` | (none) | Hugging Face token for gated repos (`hf auth login` or this variable). |
| `HF_HUB_ETAG_TIMEOUT` | `5` | Hub CLI metadata/HEAD timeout (seconds); flashcli default 5 if unset. |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `5` | Hub CLI per-request timeout (seconds); flashcli default 5 if unset. |

On download failure, the CLI suggests checking `HF_ENDPOINT` and `HF_TOKEN`.

## Behavior switches

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_SKIP_AUTO_INSTALL` | `0` | When `1`, `flashcli run` / `serve` / `pull` do **not** auto pip-install flashcli CLI deps (typer, huggingface_hub, …). Same as `--no-auto-install`. |
| `FLASHCLI_SKIP_BUNDLE_ZIP` | `0` | When `1`, **do not** download/unpack `bundle.zip` from the catalog; fails if nothing is cached. For offline or `--bundle` only. |
| `FLASHCLI_SKIP_BUNDLE_GIT` | `0` | When `1`, **do not** `git clone`/`fetch` bundle repos; fails if nothing is cached. |

Bundle Python deps (torch, etc.) are installed by `activate_bundle` from `flashcli-bundle.json` → `python_dependencies`; independent of `FLASHCLI_SKIP_AUTO_INSTALL`.

## Model / preset related

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASH_RT_PALIGEMMA_TOKENIZER` | (auto-download) | Path to the PaliGemma tokenizer **file** for Pi0.5 `post_pull`. Default cache: `~/.cache/flash_rt/`. |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | (preset/bundle) | Qwen3.6 MTP weights directory. Set via `--mtp-checkpoint` or `env` in catalog / `flashcli-bundle.json`. |

`env` blocks in `flashcli-bundle.json` or the catalog can set process env at activation (`{models_dir}`, `{bundle_root}` placeholders).

## Development

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHRT_REPO_ROOT` | (auto-detect) | FlashRT source repo root. Fallback when resolving `python_dependencies` from FlashRT `pyproject.toml` (`runtime/requirements_spec.py`). Useful in a FlashRT + flashcli monorepo. |

## Set by flashcli at runtime (informational)

| Variable | Description |
|----------|-------------|
| `FLASHCLI_ACTIVE_BUNDLE` | Absolute path of the active bundle root. |
| `FLASHCLI_ACTIVE_RUNTIME` | Same as `FLASHCLI_ACTIVE_BUNDLE` (legacy alias). |
| `PYTHONPATH` | Bundle root **prepended** for `entry` and `flash_rt` imports. |

## Related docs

- [README.md](../README.md) — quick start and cache layout
- [model_bundle_standard.md](model_bundle_standard.md) — catalog and bundle format
- [src/flashcli/catalog/models.yaml](../src/flashcli/catalog/models.yaml) — single catalog source file
