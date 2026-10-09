# Environment variables

<p align="right"><strong>English</strong> · <a href="environment.zh-CN.md">简体中文</a></p>

flashcli (the Go host) reads these variables for cache locations, FlashHub, GPU/native
preflight, weight downloads, the bundle venv, and serve. Anything not listed here has
**no effect**. Boolean flags: `1`, `true`, `yes`, `on` (case-insensitive).

## Paths and FlashHub

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_HOME` | `~/.flashcli` | Data root (`runtimes/`, `models/`, `bundles/`, `cache/`, `install.env`). |
| `FLASHCLI_RUNTIMES_DIR` | `$FLASHCLI_HOME/runtimes` | Bundle venv + `.runtime.json` markers. |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | Synced bundle tree + `.flashcli_bundle.json` markers. |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | Weights cache (`<dir>/<bundle>/<version>[@<variant>]/checkpoint/`). |
| `FLASHCLI_FLASHHUB_API` | `https://flashhub-api.aodianyun.com/api/v1/repos` | FlashHub API base for bundle refs and python-standalone. Browse at [flashhub.top](https://flashhub.top). |

## GPU / native preflight

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_CUDA_TAG` | auto | Override detected CUDA tag (`124`/`128`/`130`) for env-key matching and torch index. |
| `FLASHCLI_RUNTIME_ENV_KEY` | auto | Force the `runtime/<env-key>/` cell (e.g. `sm120-cu130-linux-x86_64-py312`). |
| `FLASHCLI_TORCH_INDEX` | auto | Override torch wheel index name (`cu124`/`cu128`). |
| `FLASHCLI_SKIP_CUDA_USERLAND` | `0` | Skip `libcublas`/`libcudart` probing/install (host CUDA userland). |
| `FLASHCLI_SKIP_NATIVE_HOST_ABI` | `0` | Skip host glibc/libstdc++ (`GLIBC_`/`GLIBCXX_`) gate against the selected `.so`. |
| `FLASHCLI_SKIP_PREFLIGHT` | `0` | Skip env-key + native cell + host ABI + CUDA preflight (debug only). |

`run`/`serve`/`pull`/`bundle sync` match the host GPU against manifest `runtime` keys, verify the
selected cell has tagged `.so`, check host glibc/libstdc++, and ensure CUDA userland
(`libcublas`/`libcudart`) — using the host loader when already present, else `pip install` the
matching `nvidia-*` wheels into the bundle venv.

## Weight downloads

Hugging Face:

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_ENDPOINT` | official Hub | Hub endpoint (e.g. `https://hf-mirror.com`). When set, only this endpoint is used. |
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | none | Token for gated repos. |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | Try `hf-mirror.com` before official Hub. |
| `FLASHCLI_NO_MIRROR` | `0` | Disable mirror fallback. |
| `FLASHCLI_SKIP_HF_PROBE` | `0` | Try official Hub without the short reachability probe. |
| `FLASHCLI_HF_DOWNLOAD_RETRIES` | `3` | Retries per endpoint (resumes partial files). |
| `FLASHCLI_HF_RETRY_DELAY` | `5` | Base delay (s) between retries (capped at 60s). |

ModelScope:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELSCOPE_ENDPOINT` | official | ModelScope API endpoint (manifest `weights.endpoint` overrides). |
| `MODELSCOPE_API_TOKEN` | none | Token for gated models. |
| `FLASHCLI_MS_DOWNLOAD_RETRIES` | `3` | Download retries. |

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_SKIP_WEIGHTS` | `0` | Skip weight download/ensure (debug; requires a cached checkpoint). |

## Bundle venv and Python

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_BUNDLE_PIP_SPEC` | — | Pip spec for `flashcli-bundle[infer]` installed into bundle venvs (e.g. a local `…/flashcli-bundle[infer]`). Highest precedence. |
| `FLASHCLI_INSTALL_REPO` / `FLASHCLI_INSTALL_REF` | from `~/.flashcli/install.env` | Git source for `flashcli-bundle[infer]` when no local checkout/spec is set. |
| `FLASHCLI_BASE_PYTHON` | auto | Base interpreter for the bundle venv. |
| `FLASHCLI_PY<abi>_BIN` | auto | Pin the interpreter for a `python_abi` (e.g. `FLASHCLI_PY312_BIN`, `FLASHCLI_PY310_BIN`). |
| `FLASHCLI_FORCE_VENV` | `0` | Rebuild the bundle venv. |
| `FLASHCLI_SKIP_VENV_SETUP` | `0` | Skip venv creation/pip (debug; use an existing venv). |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | — | pip index used when installing into bundle venvs (torch/deps). |

Standalone Python provisioning (when the bundle `python_abi` is missing):

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON` | `1` | Auto-install python-build-standalone into `$FLASHCLI_HOME/python/`. `0` disables. |
| `FLASHCLI_PYTHON_ROOT` | `$FLASHCLI_HOME/python` | Standalone Python prefix. |
| `FLASHCLI_PYTHON_ENV` | `$FLASHCLI_HOME/python-runtime.env` | Env file written with `FLASHCLI_PY<abi>_BIN=…`. |
| `FLASHCLI_PYTHON_REPO` | `{FLASHCLI_FLASHHUB_API}/flashcli-bundle/python-standalone:1.0.0` | python-standalone repo URL. |
| `FLASHCLI_PYTHON_STANDALONE_URL` | — | Direct tarball URL (overrides manifest resolution). |
| `FLASHCLI_PYTHON_STANDALONE_MANIFEST` | — | Local `python-standalone.json` path. |
| `FLASHCLI_PYTHON_STANDALONE_TAG` | `20260602` | python-build-standalone tag. |

## Behavior and upgrade

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_QUIET` | `0` | Less output from `run`/`serve`/`pull`/`sync`. |
| `FLASHCLI_GO_RELEASE_BASE` / `FLASHCLI_GO_RELEASE_API` | GitHub releases | Override for `flashcli upgrade` (e.g. Gitee). |

## Mirrors (China-friendly)

`install.sh --mirror` writes `~/.flashcli/mirror.env`; the Go host loads it at
startup (`mirror.Apply`), so it applies to bundle venv pip, HF weight downloads,
and GitHub downloads.

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASHCLI_USE_MIRROR` | `0` | Force mirror mode on. |
| `FLASHCLI_NO_MIRROR` | `0` | Force mirror mode off (wins over `mirror.env`). |
| `PIP_INDEX_URL` | (unset) | pip index for bundle venvs; `--mirror` defaults to Tsinghua. |
| `PIP_TRUSTED_HOST` | (unset) | Matching trusted host. |
| `HF_ENDPOINT` | (unset) | Hugging Face endpoint; `--mirror` defaults to `https://hf-mirror.com`. |
| `FLASHCLI_GIT_PROXY` | (unset) | GitHub proxy prefix; `--mirror` defaults to `https://gh-proxy.com/`; `0` disables. |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | Prefer hf-mirror before official Hub. |

`~/.flashcli/mirror.env` (written by `--mirror`): `FLASHCLI_USE_MIRROR=1`,
`PIP_INDEX_URL`, `PIP_TRUSTED_HOST`, `HF_ENDPOINT`, `FLASHCLI_PREFER_HF_MIRROR=1`,
`FLASHCLI_GIT_PROXY`. PyTorch wheels resolve to
`https://mirror.sjtu.edu.cn/pytorch-wheels/<cu>/` in mirror mode (else
`download.pytorch.org/whl`). The mirror must expose a PEP 503 index (project
pages like `/cu128/torch/`); Aliyun's flat `pytorch-wheels` listing is not
usable as `pip --index-url`.

Installer flags: `--mirror` / `--gitee` (also Gitee source), `--pip-mirror NAME`
(`tuna|aliyun|tencent|ustc|huawei|pypi`), `--pip-probe` (benchmark PyPI mirrors),
`--no-mirror` / `--global` (disable), `--github` (GitHub source).

## Bundle entry environment variables (engine / script)

Injected in the **bundle venv infer process** before the entry runs. Third-party entries should
rely only on the names below; other `FLASHCLI_*` values are internal.

### Script mode (`entry.*.mode: "script"`)

| Variable | Required | Description |
|----------|----------|-------------|
| `FLASHCLI_CHECKPOINT` | yes | Main weights directory (absolute, validated). |
| `FLASHCLI_BUNDLE_ROOT` | yes | Bundle root (absolute). |
| `FLASHCLI_PRESET` | yes | Preset ref string. |
| `FLASHCLI_VARIANT` | no | Set when the ref includes `@variant`. |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | no | One per manifest `extra_weights` key (uppercased; non-alphanumeric → `_`). |

### Engine mode (default)

| Source | Description |
|--------|-------------|
| manifest **`env`** / variant **`env`** | Applied before the entry; `{bundle_root}`, `{models_dir}` placeholders are expanded. |
| **`post_pull`** | e.g. `FLASH_RT_PALIGEMMA_TOKENIZER`. |
| **`--mtp-checkpoint`** | Sets `FLASHRT_QWEN36_MTP_CKPT_DIR`. |

Engine mode does **not** set `FLASHCLI_CHECKPOINT` (weights are passed to `RunEngine.load(...)`).

## Infer / serve (bundle venv)

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_HUB_OFFLINE` | `1` (set by host) | Blocks Hub network access during inference. |
| `TRANSFORMERS_OFFLINE` | `1` (set by host) | Same for `transformers`. |
| `HF_DATASETS_OFFLINE` | `1` (set by host) | Same for `datasets`. |
| `FLASHCLI_SERVE_LOG_LEVEL` | `INFO` | Application log level for `flashcli serve`. |
| `FLASHCLI_UVICORN_LOG_LEVEL` | `info` | Uvicorn access/error level. |
| `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` | `0` | Max wait when the engine is busy (`0` = no limit). |

## Internal (do not rely on in entry code)

| Variable | Description |
|----------|-------------|
| `FLASHCLI_RUNTIME_ID` | Runtime id at re-exec. |
| `FLASHCLI_IN_BUNDLE_VENV` | `1` in the infer subprocess. |
| `FLASHCLI_BUNDLE_ROOT` | Bundle root at re-exec. |
| `VIRTUAL_ENV` | Bundle venv (Python standard). |
| `LD_LIBRARY_PATH` | Extended with the venv nvidia lib dirs (`cuda`) |

## Dependency layers (pip)

| Layer | Where installed | Package / source |
|-------|-----------------|------------------|
| Host CLI | PATH | Go binary (`go/`, `install.sh`) |
| Protocol | build/dev + bundle venv | `flashcli-bundle` (`dependencies = []`) |
| Infer runtime | bundle venv | `flashcli-bundle[infer]` |
| Model stack | bundle venv | `flashcli-bundle.json` → `python_dependencies` |

The Go host never imports Python infer code. Bundle venv **must not** `pip install flashcli`.

## Related docs

- [README.md](../README.md) — quick start and cache layout
- [architecture.md](architecture.md) — host / protocol / infer flow
- [bundle_execution_abi.md](bundle_execution_abi.md) — execution backends (`entry.kind`)
