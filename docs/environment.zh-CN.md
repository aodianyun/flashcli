# 环境变量

<p align="right"><a href="environment.md">English</a> · <strong>简体中文</strong></p>

flashcli 通过环境变量配置缓存路径、preset ref、下载行为，以及与 Hugging Face / 特定 preset 的集成。未列出的变量对 flashcli **无效果**。

取值约定：`1` / `true` / `yes`（不区分大小写）视为开启布尔开关。

## 路径与 FlashHub

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_HOME` | `~/.flashcli` | 缓存根目录。默认子目录：`runtimes/`、`models/`、`cache/`。 |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | preset marker（`<bundle>/<version>@<variant>/.flashcli_bundle.json`）。 |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | Hugging Face 权重（`<dir>/<bundle>/<version>@<variant>/checkpoint/`）。 |
| `FLASHCLI_FLASHHUB_API` | `https://flashhub-api.aodianyun.com/api/v1/repos` | 短 ref `namespace/bundle:version[@variant]` 的 API 基址。在 [flashhub.top](https://flashhub.top) 浏览 bundle（API 尚未迁移至该域名）。 |

示例：

```bash
export FLASHCLI_HOME=/data/flashcli
export FLASHCLI_FLASHHUB_API=https://flashhub-api.aodianyun.com/api/v1/repos
flashcli run flashcli-bundle/pi05_libero:1.0.4
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
| `FLASHCLI_DISABLE_XET` | （未设置） | 非 `0`/`false` 时，走镜像下载会设 `HF_HUB_DISABLE_XET=1`（hf-mirror 上避免 xet）。 |
| `FLASHCLI_HF_VERBOSE` | `0` | 设为 `1` 时打印 Hub CLI 下载命令与进度细节。 |

权重下载与 `hf download` 相同；失败时请先用相同 `HF_ENDPOINT` 手动试一次 CLI。

## ModelScope（魔搭）

manifest 中 `weights.source` / `extra_weights.source` 设为 `"modelscope"` 时，由主机 CLI 调用 ModelScope SDK 拉取（`repo` 为魔搭 model id，如 `Qwen/Qwen2-7B`）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODELSCOPE_ENDPOINT` | （官方） | 自定义魔搭 API 端点；manifest 里 `weights.endpoint` 优先级更高。 |
| `MODELSCOPE_API_TOKEN` | （无） | 魔搭访问令牌（gated 模型）。 |
| `FLASHCLI_MS_DOWNLOAD_RETRIES` | `3` | ModelScope 下载重试次数。 |

`install.sh` 会安装 `modelscope>=1.11`（与 `huggingface_hub` 同为 host 权重依赖）。

`install.sh` / `auto_install.sh` 从 git 安装 `flashcli-bundle`，再装 `flashcli`（`--no-deps`）与运行时依赖（含 `huggingface_hub>=0.26`，提供 `hf` / `huggingface-cli`）。

## 行为开关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_SKIP_AUTO_INSTALL` | `0` | 设为 `1` 时，`flashcli run` / `serve` / `pull` **不**自动 pip 安装 flashcli 自身依赖（typer、huggingface_hub 等）。等价于命令行 `--no-auto-install`。 |
| `FLASHCLI_USE_MIRROR` | `0` | 设为 `1` 或存在 `~/.flashcli/mirror.env` 时：使用 `install.sh --mirror` 探测到的 PyPI 镜像、PyTorch 走阿里云、`hf-mirror.com`、bundle Python 下载走 GitHub 代理。 |
| `FLASHCLI_PIP_MIRROR` | （无） | 固定 PyPI 镜像：`tuna`、`aliyun`、`tencent`、`ustc`、`huawei`（跳过探测）。同 `install.sh --pip-mirror`。 |
| `FLASHCLI_PIP_MIRROR_PROBE` | `0` | 默认 **清华（tuna）**，不探测。设为 `1` 或 `install.sh --mirror --pip-probe` 才做 5 MiB 吞吐 benchmark。 |
| `FLASHCLI_PIP_MIRROR_PROBE_TIMEOUT` | `30` | 每个镜像探测超时（秒）。 |
| `FLASHCLI_PIP_MIRROR_PROBE_SAMPLE_BYTES` | `5242880` | 探测时每个镜像下载的字节数（HTTP Range）。 |
| `FLASHCLI_PIP_MIRROR_PROBE_PACKAGE` | `numpy` | 探测用的大 wheel 包名。 |
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
| （infer re-exec） | bundle venv | bundle venv pip 安装 **`flashcli-bundle[infer]`**，执行 `python -m flashcli_bundle.infer`。**不**加载主机 `flashcli`，**不**安装 `huggingface_hub`。 |
| `FLASHCLI_RUNTIME_ID` | （内部） | 当前激活的 runtime 标识。 |
| `FLASHCLI_BUNDLE_ROOT` | （内部） | 当前 bundle 根目录。 |

Bundle 的 Python 依赖（torch 等）由 `activate_bundle` 按 `flashcli-bundle.json` 的 `python_dependencies` 安装；与 `FLASHCLI_SKIP_AUTO_INSTALL` 无关（后者只影响 flashcli CLI 包依赖）。

## Pip 依赖分层

| 层级 | 安装位置 | 包 / 来源 | 用途 |
|------|----------|-----------|------|
| Host CLI | `~/.flashcli/venv` | `flashcli`（`pyproject.toml`） | typer、huggingface_hub、sync/pull |
| Protocol | 主机 venv | `flashcli-bundle`（无 extras） | manifest、options、native 校验 |
| Infer runtime | Bundle venv | `flashcli-bundle[infer]` | `python -m flashcli_bundle.infer`、fastapi/uvicorn |
| Model stack | Bundle venv | `flashcli-bundle.json` → `python_dependencies` | torch、transformers… |

主机**禁止** `import flashcli_bundle.infer`。Bundle venv **禁止** `pip install flashcli`。

## 主机 CLI 与 bundle infer

见 [architecture.zh-CN.md](architecture.zh-CN.md#主机-cli-与-bundle-infer必读)。**不要**在 bundle venv 内 `pip install flashcli`。

## 模型与 preset 相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASH_RT_PALIGEMMA_TOKENIZER` | （自动下载） | **Engine 模式**：Pi0.5 `post_pull` 写入的 PaliGemma tokenizer 文件路径。 |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | （manifest / CLI） | **Engine 模式**：Qwen3.6 MTP 权重目录；manifest `env` 或 `--mtp-checkpoint` 注入。 |

`flashcli-bundle.json` 中的顶层 / variant **`env:`** 块仅在 **engine 模式** entry 执行前写入（见下方「Bundle entry 环境变量」）。Script 模式不使用 manifest `env` 注入权重路径，改由平台变量 `FLASHCLI_*` 提供已解析的绝对路径。

## Bundle entry 环境变量（engine / script）

以下变量在 **bundle venv infer 进程**内、调用 `RunEngine` / `ServeEngine` 或 script `main(argv)` **之前**由 flashcli 注入。第三方 entry 只应依赖本表列出的名称；其余 `FLASHCLI_*`（如 `FLASHCLI_RUNTIME_ID`）为内部实现，**不保证稳定**。

### Script 模式（`entry.*.mode: "script"`）

| 变量 | 必有 | 说明 |
|------|------|------|
| `FLASHCLI_CHECKPOINT` | 是 | 当前 preset 的**主权重**目录（绝对路径，已通过 cache 校验）。 |
| `FLASHCLI_BUNDLE_ROOT` | 是 | 当前 bundle 根目录（绝对路径）。 |
| `FLASHCLI_PRESET` | 是 | 当前 preset ref 字符串（与 CLI  positional ref 一致）。 |
| `FLASHCLI_VARIANT` | 否 | 若 ref 含 `@variant` 则写入；否则不设置。 |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | 否 | 每个 manifest `extra_weights` 条目一条；`<KEY>` 为大写 manifest 键（非字母数字转为 `_`）。值为该扩展权重的**绝对路径**（已校验存在）。例：`extra_weights.mtp_fp8` → `FLASHCLI_EXTRA_WEIGHT_MTP_FP8`。 |

Script entry **不应**依赖 `{models_dir}` 占位符或全局 cache 布局；只读上表变量即可。

### Engine 模式（默认）

| 来源 | 说明 |
|------|------|
| manifest **`env`** / variant **`env`** | 在 entry 执行前写入；支持 `{bundle_root}`、`{models_dir}` 占位符。由 bundle 作者命名（如 Qwen 的 `FLASHRT_QWEN36_MTP_CKPT_DIR`）。 |
| **`post_pull`** | 按 manifest 步骤写入（如 `FLASH_RT_PALIGEMMA_TOKENIZER`）。 |
| **`--mtp-checkpoint`** | 覆盖并写入 `FLASHRT_QWEN36_MTP_CKPT_DIR`（仅 engine 主机/infer 解析该 flag）。 |

Engine 模式**不**设置 `FLASHCLI_CHECKPOINT`（权重通过 `RunEngine.load(path, …)` 传入）。

### 内部变量（entry 请勿依赖）

| 变量 | 说明 |
|------|------|
| `FLASHCLI_RUNTIME_ID` | re-exec 时当前 runtime 矩阵键。 |
| `FLASHCLI_IN_BUNDLE_VENV` | `1` 表示 infer 子进程。 |
| `FLASHCLI_BUNDLE_ROOT`（re-exec 时） | flashcli 内部解析 manifest 用；script 模式由 entry 注入覆盖为同一语义的路径。 |
| `VIRTUAL_ENV` | bundle venv 路径（Python 标准）。 |

## Infer / serve（bundle venv）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_HUB_OFFLINE` | `1`（flashcli 设置） | bundle 推理阶段禁止访问 Hugging Face Hub。权重与 `extra_weights` 须由 `flashcli pull` 或 `run`/`serve` 主机预检准备好。 |
| `TRANSFORMERS_OFFLINE` | `1`（flashcli 设置） | 同上，作用于 `transformers` / `AutoTokenizer` — 本地 tokenizer 不完整时快速失败。 |
| `HF_DATASETS_OFFLINE` | `1`（flashcli 设置） | infer 子进程禁止访问 datasets hub。 |
| `FLASHCLI_SERVE_LOG_LEVEL` | `INFO` | `flashcli serve` 应用日志级别。 |
| `FLASHCLI_UVICORN_LOG_LEVEL` | `info` | Uvicorn 访问/错误日志级别。 |
| `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` | `0` | 引擎忙碌时最长等待秒数（`0` = 不限制）。 |

## 开发与调试

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_DEBUG` | （未设置） | 设置后 CLI 错误打印完整 traceback。 |
| `FLASHCLI_INSTALL_REPO` / `FLASHCLI_INSTALL_REF` | （来自 `install.env`） | bundle venv 安装 `flashcli-bundle` 时的 git 源。 |
| `FLASHCLI_REFRESH_RELEASE_CACHE` | （未设置） | 设为 `1` 时刷新 python-build-standalone 的 GitHub release JSON 缓存。 |
| `FLASHCLI_PYTHON_RELEASE_CACHE` | `~/.flashcli/python/.cache` | standalone Python release 索引 JSON 缓存目录。 |
| `GITHUB_TOKEN` / `GH_TOKEN` | （无） | 拉取 python-build-standalone release 时可选 GitHub API token。 |
| `FLASHRT_REPO_ROOT` | （自动探测） | FlashRT 源码仓库根目录。在无法从 bundle 的 `flashcli-bundle.json` 解析 `python_dependencies` 时，用于回退读取 FlashRT 的 `pyproject.toml`（见 `runtime/requirements_spec.py`）。本地 FlashRT + flashcli monorepo 时偶尔需要。 |

## 运行时由 flashcli 设置（内部 / 调试）

以下变量由 flashcli 在 re-exec 或 activate 流程中写入，**不属于 bundle entry 稳定 API**（见上一节「Bundle entry 环境变量」）：

| 变量 | 说明 |
|------|------|
| `PYTHONPATH` | **Activate：** 通过 `sys.path` prepend bundle 根目录以便 `import entry` / `flash_rt`。**Re-exec：** 清除 host `PYTHONPATH`。 |

## 相关文档

- [README.zh-CN.md](../README.zh-CN.md) — 快速开始与本机缓存路径
- [architecture.zh-CN.md](architecture.zh-CN.md) — host / protocol / infer 流程
- [module_layers.zh-CN.md](module_layers.zh-CN.md) — 模块归属规则
- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — preset ref 与运行时流程
