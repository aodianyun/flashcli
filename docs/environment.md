# Environment variables

<p align="right"><strong>English</strong> · <a href="environment.zh-CN.md">简体中文</a></p>

flashcli uses environment variables for cache locations, preset refs, download behavior, and Hugging Face / preset-specific integration. Variables not listed here have **no effect** on flashcli.

Boolean flags: `1`, `true`, or `yes` (case-insensitive) enable the switch.

## Paths and FlashHub

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_HOME` | `~/.flashcli` | Cache root. Default subdirs: `runtimes/`, `models/`, `bundles/`, `cache/`. |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | Preset marker cache (`<bundle>/<version>@<variant>/.flashcli_bundle.json`). |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | Hugging Face weights (`<dir>/<bundle>/<version>@<variant>/checkpoint/`). |
| `FLASHCLI_FLASHHUB_API` | `https://flashhub-api.aodianyun.com/api/v1/repos` | Base URL for short refs `namespace/bundle:version[@variant]`. |

Example:

```bash
export FLASHCLI_HOME=/data/flashcli
export FLASHCLI_FLASHHUB_API=https://flashhub-api.aodianyun.com/api/v1/repos
flashcli run flashcli-bundle/pi05_libero:1.0.3
flashcli models list
```

## GPU / CUDA and native libraries

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_CUDA_TAG` | (auto-detect) | Override detected CUDA userland tag (`124` / `128` / `130`) used to pick native `.so` under `runtime/<env-key>/`. |
| (automatic) | — | If `nvcc` is missing, flashcli infers from `nvidia-smi` banner (`CUDA Version: 13.0` → `130`); SM89 no longer hard-defaults to `124`. |

`flashcli run` selects native `.so` by **sm + cuda + os + arch + Python**. If `libcublas.so.12` is missing on CUDA 13 hosts, update flashcli or set `export FLASHCLI_CUDA_TAG=130`.

## Downloads and Hugging Face

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_ENDPOINT` | (official Hub) | Hub endpoint override. Mirror example: `https://hf-mirror.com`. When set, flashcli uses only that endpoint. |
| (automatic) | — | If `HF_ENDPOINT` is **not** set, flashcli tries official Hub first, then mirror (internally via `hf download`). |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | When `1`, try mirror before official Hub. |
| `HF_TOKEN` | (none) | Hugging Face token for gated repos (`hf auth login` or this variable). |
| `HF_HUB_ETAG_TIMEOUT` | `30` | Hub CLI metadata/HEAD timeout (seconds); flashcli default 30 if unset. |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `300` | Hub CLI per-request timeout (seconds); flashcli default 300 if unset. |
| `FLASHCLI_HF_ETAG_TIMEOUT` | `30` | Used only when `HF_HUB_ETAG_TIMEOUT` is unset. |
| `FLASHCLI_HF_DOWNLOAD_TIMEOUT` | `300` | Used only when `HF_HUB_DOWNLOAD_TIMEOUT` is unset. |
| `FLASHCLI_HF_DOWNLOAD_RETRIES` | `3` | Retries per endpoint on transient failures (resume partial downloads). |
| `FLASHCLI_HF_RETRY_DELAY` | `5` | Base delay (seconds) between retries; grows linearly up to 60s. |
| `FLASHCLI_HF_MAX_WORKERS` | (Hub default) | Pass `--max-workers` to `hf download` (e.g. `1` on flaky networks). |
| `FLASHCLI_HF_PROBE_TIMEOUT` | `3` | Timeout (seconds) for probing official Hub reachability before fallback. |
| `FLASHCLI_SKIP_HF_PROBE` | `0` | When `1`, skip probe and still try official first (may be slower under blocked networks). |
| `FLASHCLI_DISABLE_XET` | (unset) | When not `0`/`false`, mirror downloads set `HF_HUB_DISABLE_XET=1` (avoids xet on hf-mirror.com). |
| `FLASHCLI_HF_VERBOSE` | `0` | When `1`, print Hub CLI download commands and progress details. |

Weight download behavior matches `hf download`; on failures, test the same `HF_ENDPOINT` manually with Hub CLI.

## ModelScope

When `weights.source` / `extra_weights.source` is `"modelscope"`, the host CLI pulls via the ModelScope SDK (`repo` is the ModelScope model id).

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELSCOPE_ENDPOINT` | (official) | Custom ModelScope API endpoint; manifest `weights.endpoint` overrides. |
| `MODELSCOPE_API_TOKEN` | (none) | ModelScope token for gated models. |
| `FLASHCLI_MS_DOWNLOAD_RETRIES` | `3` | ModelScope download retries. |

`install.sh` installs `modelscope>=1.11` alongside `huggingface_hub` for host weight pulls.

`install.sh` / `auto_install.sh` install `flashcli-bundle` from git, then `flashcli` (`--no-deps`) and runtime deps including `huggingface_hub>=0.26` (`hf` / `huggingface-cli`). Post-install verification also checks Hub CLI availability; if scripts dir is not on `PATH`, flashcli falls back to `python -m huggingface_hub.cli.hf`.

## Behavior switches

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_SKIP_AUTO_INSTALL` | `0` | When `1`, `flashcli run` / `serve` / `pull` do **not** auto pip-install flashcli CLI deps (typer, huggingface_hub, …). Same as `--no-auto-install`. |
| `FLASHCLI_USE_MIRROR` | `0` | When `1` or `~/.flashcli/mirror.env` exists: probed China PyPI mirror (from `install.sh --mirror`), Aliyun PyTorch wheels, `hf-mirror.com`, and GitHub release proxy for bundle Python downloads. |
| `FLASHCLI_PIP_MIRROR` | (none) | Pin PyPI mirror: `tuna`, `aliyun`, `tencent`, `ustc`, `huawei` (skips probe). Same as `install.sh --pip-mirror`. |
| `FLASHCLI_PIP_MIRROR_PROBE` | `0` | Default: **Tsinghua (tuna)** without probing. Set `1` or use `install.sh --mirror --pip-probe` to benchmark mirrors (5 MiB sample). |
| `FLASHCLI_PIP_MIRROR_PROBE_TIMEOUT` | `30` | Per-mirror probe timeout (seconds). |
| `FLASHCLI_PIP_MIRROR_PROBE_SAMPLE_BYTES` | `5242880` | Bytes downloaded per mirror during probe (HTTP Range). |
| `FLASHCLI_PIP_MIRROR_PROBE_PACKAGE` | `numpy` | PEP 503 package used for large-wheel throughput probe. |
| `FLASHCLI_NO_MIRROR` | `0` | When `1`, ignore mirror mode even if `mirror.env` exists. |
| `FLASHCLI_GIT_PROXY` | (mirror default) | GitHub HTTPS proxy for release downloads (e.g. `https://mirror.ghproxy.com/`). `--mirror` sets this; `0` disables. |
| `FLASHCLI_PREFER_GITHUB_MIRROR` | `0` | When `1`, try GitHub proxy before direct GitHub (also default when mirror mode is on). |
| `FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON` | `1` | When `1`, if the bundle’s `python_abi` (e.g. 3.12) is missing, download **python-build-standalone** into `$FLASHCLI_HOME/python/` and use it for the bundle venv. Uses GitHub mirror when mirror mode is on. Does **not** modify system `/usr/bin/python3`. Set `0` to disable. |
| `FLASHCLI_PYTHON_ROOT` | `$FLASHCLI_HOME/python` | Standalone Python install prefix (bundle runtime). Matrix builds may use `/opt/flashcli-python` when set explicitly. |
| `FLASHCLI_PYTHON_ENV` | `$FLASHCLI_HOME/python-runtime.env` | Env file written with `FLASHCLI_PY312_BIN=…` after auto-install (sourced on next resolve). |
| `FLASHCLI_PY312_BIN` | (auto) | Override path to Python 3.12 for bundle venv / native ABI probes. Also `FLASHCLI_PY310_BIN`, `FLASHCLI_PY311_BIN`, … |
| `FLASHCLI_PYTHON_STANDALONE_TAG` | `20260602` | Upstream python-build-standalone release tag (GitHub fallback). |
| `FLASHCLI_PYTHON_REPO` | [FlashHub 1.0.0](https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/python-standalone/1.0.0) | **Preferred** source for `python-standalone.json` + tarballs; on failure → GitHub → GitHub proxy. Set `0` to skip FlashHub. |
| `FLASHCLI_PYTHON_STANDALONE_MANIFEST` | (none) | Local manifest path (fallback before GitHub when FlashHub fails). |
| `FLASHCLI_RUNTIMES_DIR` | `$FLASHCLI_HOME/runtimes` | Bundle runtime cache (bundle root, `runtime/`, venv). |
| `FLASHCLI_IN_BUNDLE_VENV` | (internal) | `1` when the infer subprocess is running inside the bundle venv. |
| (infer re-exec) | bundle venv | Bundle venv pip-installs **`flashcli-bundle[infer]`** and runs `python -m flashcli_bundle.infer`. Does **not** load host `flashcli` or `huggingface_hub`. |
| `FLASHCLI_RUNTIME_ID` | (internal) | Active runtime identifier. |
| `FLASHCLI_BUNDLE_ROOT` | (internal) | Active bundle root directory. |

Bundle Python deps (torch, etc.) are installed by `activate_bundle` from `flashcli-bundle.json` → `python_dependencies`; independent of `FLASHCLI_SKIP_AUTO_INSTALL`.

## Dependency layers (pip)

| Layer | Where installed | Package / source | Purpose |
|-------|-----------------|------------------|---------|
| Host CLI | `~/.flashcli/venv` | `flashcli` (`pyproject.toml`) | typer, huggingface_hub, sync/pull |
| Protocol | Host venv | `flashcli-bundle` (no extras) | manifest, options, native validation |
| Infer runtime | Bundle venv | `flashcli-bundle[infer]` | `python -m flashcli_bundle.infer`, fastapi/uvicorn |
| Model stack | Bundle venv | `flashcli-bundle.json` → `python_dependencies` | torch, transformers, … |

Host **must not** `import flashcli_bundle.infer`. Bundle venv **must not** `pip install flashcli`.

## Host CLI vs bundle infer

See [architecture.md](architecture.md#host-cli-vs-bundle-infer-important). Do **not** `pip install flashcli` into bundle venvs.

## Model / preset related

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASH_RT_PALIGEMMA_TOKENIZER` | (auto-download) | Path to the PaliGemma tokenizer **file** for Pi0.5 `post_pull`. Default cache: `~/.cache/flash_rt/`. |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | (preset/bundle) | Qwen3.6 MTP weights directory. Set via `--mtp-checkpoint` or `env` in `flashcli-bundle.json`. |

`env` blocks in `flashcli-bundle.json` can set process env at activation (`{models_dir}`, `{bundle_root}` placeholders).

## Infer / serve (bundle venv)

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_SERVE_LOG_LEVEL` | `INFO` | Application log level for `flashcli serve`. |
| `FLASHCLI_UVICORN_LOG_LEVEL` | `info` | Uvicorn access/error log level. |
| `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` | `0` | Max seconds to wait when the engine is busy (`0` = no limit). |

## Development and debugging

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_DEBUG` | (unset) | When set, print full tracebacks for CLI errors. |
| `FLASHCLI_INSTALL_REPO` / `FLASHCLI_INSTALL_REF` | (from `install.env`) | Git source for `flashcli-bundle` when installing into bundle venvs. |
| `FLASHCLI_REFRESH_RELEASE_CACHE` | (unset) | When `1`, refresh cached python-build-standalone GitHub release JSON. |
| `FLASHCLI_PYTHON_RELEASE_CACHE` | `~/.flashcli/python/.cache` | Cache dir for standalone Python release index JSON. |
| `GITHUB_TOKEN` / `GH_TOKEN` | (none) | Optional token for GitHub API when fetching python-build-standalone releases. |
| `FLASHRT_REPO_ROOT` | (auto-detect) | FlashRT source repo root. Fallback when resolving `python_dependencies` from FlashRT `pyproject.toml` (`runtime/requirements_spec.py`). Useful in a FlashRT + flashcli monorepo. |

## Set by flashcli at runtime (informational)

| Variable | Description |
|----------|-------------|
| `FLASHCLI_ACTIVE_BUNDLE` | Absolute path of the active bundle root. |
| `FLASHCLI_BUNDLE_ROOT` | Active bundle root (set during re-exec). |
| `PYTHONPATH` | **Activate:** bundle root prepended for `entry` / `flash_rt`. **Re-exec:** host `flashcli` is not on `PYTHONPATH`. |

## Related docs

- [README.md](../README.md) — quick start and cache layout
- [architecture.md](architecture.md) — host / protocol / infer flow
- [module_layers.md](module_layers.md) — module placement rules
- [model_bundle_standard.md](model_bundle_standard.md) — preset ref and runtime flow
