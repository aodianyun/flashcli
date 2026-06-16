# 环境变量

<p align="right"><a href="environment.md">English</a> · <strong>简体中文</strong></p>

flashcli 通过环境变量配置缓存路径、catalog、下载行为，以及与 Hugging Face / 特定 preset 的集成。未列出的变量对 flashcli **无效果**。

取值约定：`1` / `true` / `yes`（不区分大小写）视为开启布尔开关。

## 路径与 catalog

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_HOME` | `~/.flashcli` | 缓存根目录。默认子目录：`runtimes/`、`models/`、`cache/`。旧版：`bundles/`（v3 之前的 zip 缓存）。 |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | 旧版 bundle 缓存路径。新 sync 使用 `FLASHCLI_RUNTIMES_DIR` / `runtimes/`。 |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | 覆盖 Hugging Face 权重缓存根目录（各 preset 一般为 `<dir>/<preset>/checkpoint/`）。 |
| `FLASHCLI_MODELS_YAML` | （内置） | **覆盖 preset catalog 文件路径**。默认使用安装包内 `flashcli/catalog/models.yaml`（pip wheel 与 editable 相同）。指向的文件必须存在。 |

维护 catalog 时通常**直接改**仓库内 [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)；仅在多版本并存、CI 或容器内挂载自定义 catalog 时设置 `FLASHCLI_MODELS_YAML`。

示例：

```bash
export FLASHCLI_HOME=/data/flashcli
export FLASHCLI_MODELS_YAML=/etc/flashcli/models.yaml
flashcli models list
```

## GPU / CUDA 与 native 库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_CUDA_TAG` | （自动） | 覆盖自动检测的 CUDA 用户态标签（`124` / `128` / `130`），用于从 bundle `runtime/` 选择 `cu124` / `cu130` 等 `.so`。 |
| （自动） | — | 无 `nvcc` 时从 `nvidia-smi` 横幅 `CUDA Version: 13.0` 推断 `130`；SM89 不再默认 `124`。 |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | （自动） | PyPI 镜像；`flashcli run` 安装 bundle 依赖时会传给 pip（mirror 模式见下方行为开关）。 |

`flashcli run` 会按 **sm + cuda + os + arch + Python** 从 bundle 的 `runtime/<env-key>/` 加载 `.so`；若 `libcublas.so.12` 缺失而驱动为 CUDA 13，请更新 flashcli 或设 `export FLASHCLI_CUDA_TAG=130`。

## 下载与 Hugging Face

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_ENDPOINT` | （官方 Hub） | **官方镜像开关**（与 `hf download` / `huggingface-cli download` 相同）。例：`https://hf-mirror.com`。设置后 flashcli 只走该端点。 |
| （自动） | — | 未设置 `HF_ENDPOINT` 时：先试官方 Hub，失败再试镜像（内部调用 `hf download`）。 |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | 设为 `1` 时改为先镜像、再官方 Hub。 |
| `HF_TOKEN` | （无） | Hugging Face 访问令牌；gated 模型需 `hf auth login` 或设置此变量。 |
| `HF_HUB_ETAG_TIMEOUT` | `30` | Hub CLI：元数据/HEAD 超时（秒）；未设时 flashcli 默认 30。 |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `300` | Hub CLI：单次 HTTP 超时（秒）；未设时 flashcli 默认 300。 |
| `FLASHCLI_HF_ETAG_TIMEOUT` | `30` | 仅当未设置 `HF_HUB_ETAG_TIMEOUT` 时生效。 |
| `FLASHCLI_HF_DOWNLOAD_TIMEOUT` | `300` | 仅当未设置 `HF_HUB_DOWNLOAD_TIMEOUT` 时生效。 |
| `FLASHCLI_HF_DOWNLOAD_RETRIES` | `3` | 每个端点的重试次数；失败后会保留已下载文件并断点续传。 |
| `FLASHCLI_HF_RETRY_DELAY` | `5` | 重试间隔基数（秒），线性递增，上限 60s。 |
| `FLASHCLI_HF_MAX_WORKERS` | （Hub 默认） | 传给 `hf download` 的 `--max-workers`（网络不稳时可设为 `1`）。 |
| `FLASHCLI_HF_PROBE_TIMEOUT` | `3` | 探测官方 Hub 是否可达（秒）；不可达则跳过官方、直接镜像。 |
| `FLASHCLI_SKIP_HF_PROBE` | `0` | 设为 `1` 时不做探测，仍先试官方（`hf` 内部会慢重试）。 |

权重下载与 `hf download` 相同；失败时请先用相同 `HF_ENDPOINT` 手动试一次 CLI。

`install.sh` / `auto_install.sh` 从 git 安装 `flashcli-bundle`，再装 `flashcli`（`--no-deps`）与运行时依赖（含 `huggingface_hub>=0.26`，提供 `hf` / `huggingface-cli`）。

## 行为开关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_SKIP_AUTO_INSTALL` | `0` | 设为 `1` 时，`flashcli run` / `serve` / `pull` **不**自动 pip 安装 flashcli 自身依赖（typer、huggingface_hub 等）。等价于命令行 `--no-auto-install`。 |
| `FLASHCLI_USE_MIRROR` | `0` | 设为 `1` 或存在 `~/.flashcli/mirror.env` 时：PyPI/PyTorch 走阿里云、`hf-mirror.com`、bundle Python 下载走 GitHub 代理。`install.sh --mirror` 会写入。 |
| `FLASHCLI_NO_MIRROR` | `0` | 设为 `1` 时忽略 mirror 模式（即使存在 `mirror.env`）。 |
| `FLASHCLI_GIT_PROXY` | （mirror 默认） | GitHub 发布包下载代理（如 `https://mirror.ghproxy.com/`）。`--mirror` 会设置；设为 `0` 关闭。 |
| `FLASHCLI_PREFER_GITHUB_MIRROR` | `0` | 设为 `1` 时优先 GitHub 代理再直连（mirror 模式默认如此）。 |
| `FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON` | `1` | 设为 `1` 时，若 bundle 要求的 `python_abi`（如 3.12）本机不存在，则下载 **python-build-standalone** 到 `$FLASHCLI_HOME/python/`，用于创建 bundle venv。mirror 模式下走 GitHub 代理。**不会**修改系统 `/usr/bin/python3`。设为 `0` 关闭。 |
| `FLASHCLI_PYTHON_ROOT` | `$FLASHCLI_HOME/python` | standalone Python 安装前缀（bundle 运行时）。矩阵构建可显式设为 `/opt/flashcli-python`。 |
| `FLASHCLI_PYTHON_ENV` | `$FLASHCLI_HOME/python-runtime.env` | 自动安装后写入 `FLASHCLI_PY312_BIN=…` 等（下次解析时会加载）。 |
| `FLASHCLI_PY312_BIN` | （自动） | 覆盖 bundle venv / native ABI 探测用的 Python 3.12 路径。另有 `FLASHCLI_PY310_BIN`、`FLASHCLI_PY311_BIN` 等。 |
| `FLASHCLI_PYTHON_STANDALONE_TAG` | `20260602` | python-build-standalone 上游 release tag（GitHub fallback 用）。 |
| `FLASHCLI_PYTHON_REPO` | [FlashHub 1.0.0](https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/python-standalone/1.0.0) | **优先**从此 FlashHub 仓库拉 `python-standalone.json` 与 tarball；失败再 GitHub → GitHub 代理。设为 `0` 跳过 FlashHub。 |
| `FLASHCLI_PYTHON_STANDALONE_MANIFEST` | （无） | 本地 manifest 路径（FlashHub 不可用时的 fallback，在 GitHub 之前）。 |
| `FLASHCLI_RUNTIMES_DIR` | `$FLASHCLI_HOME/runtimes` | bundle runtime 缓存（bundle 根、`runtime/`、venv）。 |
| `FLASHCLI_IN_BUNDLE_VENV` | （内部） | `1` 表示当前进程已在 bundle venv 的 infer 子进程内。 |
| （infer re-exec） | 主机安装 + bundle venv | **flashcli 只装一份**（主机 venv）；bundle venv 的 Python 通过 `PYTHONPATH` 加载主机上的 `flashcli`，执行 `python -m flashcli.runtime.infer`。bundle venv 内只会 pip 安装 infer 的**依赖**（typer、pyyaml、fastapi 等），**不会**安装 `huggingface_hub` 或 flashcli 包本身。 |
| `FLASHCLI_RUNTIME_ID` | （内部） | 当前激活的 runtime 标识。 |
| `FLASHCLI_BUNDLE_ROOT` | （内部） | 当前 bundle 根目录。 |

Bundle 的 Python 依赖（torch 等）由 `activate_bundle` 按 `flashcli-bundle.json` 的 `python_dependencies` 安装；与 `FLASHCLI_SKIP_AUTO_INSTALL` 无关（后者只影响 flashcli CLI 包依赖）。

## 主机 CLI 与 bundle infer

见 [architecture.zh-CN.md](architecture.zh-CN.md#主机-cli-与-bundle-infer必读)。**不要**在 bundle venv 内 `pip install flashcli`。

## 模型与 preset 相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASH_RT_PALIGEMMA_TOKENIZER` | （自动下载） | Pi0.5 `post_pull` 使用的 PaliGemma tokenizer **文件**路径。未设置时下载到 `~/.cache/flash_rt/`。可提前指定以避免重复下载或离线使用。 |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | （preset/bundle） | Qwen3.6 MTP 权重目录。可由 `flashcli run` / `serve` 的 `--mtp-checkpoint` 设置，或写在 catalog / `flashcli-bundle.json` 的 `env` 段。 |

`flashcli-bundle.json` 与 catalog 中的 `env:` 块可在激活 bundle 时写入进程环境（支持 `{models_dir}`、`{bundle_root}` 占位符）。

## 开发与维护

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHRT_REPO_ROOT` | （自动探测） | FlashRT 源码仓库根目录。在无法从 bundle 的 `flashcli-bundle.json` 解析 `python_dependencies` 时，用于回退读取 FlashRT 的 `pyproject.toml`（见 `runtime/requirements_spec.py`）。本地开发 FlashRT + flashcli  monorepo 时偶尔需要。 |

## 运行时由 flashcli 设置（只读 / 调试）

以下变量由 flashcli 在 `activate_bundle` 或推理流程中**写入**当前进程，一般无需用户设置；bundle 内 `entry` 模块可读取：

| 变量 | 说明 |
|------|------|
| `FLASHCLI_ACTIVE_BUNDLE` | 当前激活的 bundle 根目录绝对路径。 |
| `FLASHCLI_ACTIVE_RUNTIME` | 与 `FLASHCLI_ACTIVE_BUNDLE` 相同（兼容旧名）。 |
| `PYTHONPATH` | **Activate** 时 prepend bundle 根目录（`entry` / `flash_rt`）。**Re-exec** 时先 prepend 主机 flashcli（见 [architecture.zh-CN.md](architecture.zh-CN.md#主机-cli-与-bundle-infer必读)）。 |

## 相关文档

- [README.zh-CN.md](../README.zh-CN.md) — 快速开始与本机缓存路径
- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — catalog + 运行时流程
- [src/flashcli/catalog/models.yaml](../src/flashcli/catalog/models.yaml) — preset catalog 唯一源文件
