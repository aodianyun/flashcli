# 环境变量

<p align="right"><a href="environment.md">English</a> · <strong>简体中文</strong></p>

flashcli（Go host）读取以下变量用于缓存路径、FlashHub、GPU/原生预检、权重下载、bundle venv 与
serve。未列出的变量**无效**。布尔开关：`1`、`true`、`yes`、`on`（大小写不敏感）。

## 路径与 FlashHub

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_HOME` | `~/.flashcli` | 数据根（`runtimes/`、`models/`、`bundles/`、`cache/`、`install.env`）。 |
| `FLASHCLI_RUNTIMES_DIR` | `$FLASHCLI_HOME/runtimes` | bundle venv 与 `.runtime.json` marker。 |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | 同步后的 bundle 树与 `.flashcli_bundle.json` marker。 |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | 权重缓存（`<dir>/<bundle>/<version>[@<variant>]/checkpoint/`）。 |
| `FLASHCLI_FLASHHUB_API` | `https://flashhub-api.aodianyun.com/api/v1/repos` | bundle ref 与 python-standalone 的 FlashHub API 基址；浏览 [flashhub.top](https://flashhub.top)。 |

## GPU / 原生预检

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_CUDA_TAG` | 自动 | 覆盖检测到的 CUDA tag（`124`/`128`/`130`），用于 env key 匹配与 torch index。 |
| `FLASHCLI_RUNTIME_ENV_KEY` | 自动 | 强制 `runtime/<env-key>/`（如 `sm120-cu130-linux-x86_64-py312`）。 |
| `FLASHCLI_TORCH_INDEX` | 自动 | 覆盖 torch wheel index 名（`cu124`/`cu128`）。 |
| `FLASHCLI_SKIP_CUDA_USERLAND` | `0` | 跳过 `libcublas`/`libcudart` 探测/安装。 |
| `FLASHCLI_SKIP_NATIVE_HOST_ABI` | `0` | 跳过针对所选 `.so` 的 glibc/libstdc++（`GLIBC_`/`GLIBCXX_`）门禁。 |
| `FLASHCLI_SKIP_PREFLIGHT` | `0` | 跳过 env key + native cell + host ABI + CUDA 预检（仅调试）。 |

`run`/`serve`/`pull`/`bundle sync` 会把本机 GPU 与 manifest `runtime` 匹配、校验所选 cell 的
`.so`、检查 host glibc/libstdc++，并确保 CUDA userland（`libcublas`/`libcudart`）——宿主已提供则
直接用宿主 loader，否则把匹配的 `nvidia-*` wheel 装进 bundle venv。

## 权重下载

Hugging Face：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_ENDPOINT` | 官方 Hub | Hub 端点（如 `https://hf-mirror.com`）。设置后只用该端点。 |
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | 无 | gated repo 令牌。 |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | 先试 `hf-mirror.com`。 |
| `FLASHCLI_NO_MIRROR` | `0` | 关闭镜像回退。 |
| `FLASHCLI_SKIP_HF_PROBE` | `0` | 不做可达性探测，直接试官方 Hub。 |
| `FLASHCLI_HF_DOWNLOAD_RETRIES` | `3` | 每端点重试次数（可续传）。 |
| `FLASHCLI_HF_RETRY_DELAY` | `5` | 重试基础间隔（秒，最多 60s）。 |

ModelScope：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODELSCOPE_ENDPOINT` | 官方 | ModelScope API 端点（manifest `weights.endpoint` 优先）。 |
| `MODELSCOPE_API_TOKEN` | 无 | gated 模型令牌。 |
| `FLASHCLI_MS_DOWNLOAD_RETRIES` | `3` | 下载重试次数。 |

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_SKIP_WEIGHTS` | `0` | 跳过权重下载/校验（调试；需已有缓存 checkpoint）。 |

## Bundle venv 与 Python

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_BUNDLE_PIP_SPEC` | — | 装进 bundle venv 的 `flashcli-bundle[infer]` pip spec（如本地 `…/flashcli-bundle[infer]`）。优先级最高。 |
| `FLASHCLI_INSTALL_REPO` / `FLASHCLI_INSTALL_REF` | 来自 `~/.flashcli/install.env` | 无本地 checkout/spec 时，`flashcli-bundle[infer]` 的 git 来源。 |
| `FLASHCLI_BASE_PYTHON` | 自动 | bundle venv 的基础解释器。 |
| `FLASHCLI_PY<abi>_BIN` | 自动 | 固定某 `python_abi` 的解释器（如 `FLASHCLI_PY312_BIN`、`FLASHCLI_PY310_BIN`）。 |
| `FLASHCLI_FORCE_VENV` | `0` | 重建 bundle venv。 |
| `FLASHCLI_SKIP_VENV_SETUP` | `0` | 跳过 venv 创建/pip（调试；用已有 venv）。 |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | — | 装入 bundle venv（torch/依赖）时使用的 pip 索引。 |

Standalone Python 自动供给（当 bundle `python_abi` 缺失）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON` | `1` | 自动把 python-build-standalone 装到 `$FLASHCLI_HOME/python/`。`0` 关闭。 |
| `FLASHCLI_PYTHON_ROOT` | `$FLASHCLI_HOME/python` | standalone Python 前缀。 |
| `FLASHCLI_PYTHON_ENV` | `$FLASHCLI_HOME/python-runtime.env` | 写入 `FLASHCLI_PY<abi>_BIN=…` 的 env 文件。 |
| `FLASHCLI_PYTHON_REPO` | `{FLASHCLI_FLASHHUB_API}/flashcli-bundle/python-standalone:1.0.0` | python-standalone repo URL。 |
| `FLASHCLI_PYTHON_STANDALONE_URL` | — | 直接指定 tarball URL（覆盖 manifest 解析）。 |
| `FLASHCLI_PYTHON_STANDALONE_MANIFEST` | — | 本地 `python-standalone.json` 路径。 |
| `FLASHCLI_PYTHON_STANDALONE_TAG` | `20260602` | python-build-standalone tag。 |

## 行为与升级

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_QUIET` | `0` | 减少 `run`/`serve`/`pull`/`sync` 输出。 |
| `FLASHCLI_GO_RELEASE_BASE` / `FLASHCLI_GO_RELEASE_API` | GitHub releases | `flashcli upgrade` 覆盖（如 Gitee）。 |

## 镜像（国内友好）

`install.sh --mirror` 会写 `~/.flashcli/mirror.env`；Go host 启动时加载（`mirror.Apply`），
因此对 bundle venv 的 pip、HF 权重下载、GitHub 下载一并生效。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_USE_MIRROR` | `0` | 强制开启镜像。 |
| `FLASHCLI_NO_MIRROR` | `0` | 强制关闭（优先于 `mirror.env`）。 |
| `PIP_INDEX_URL` | （无） | bundle venv 的 pip 索引；`--mirror` 默认清华。 |
| `PIP_TRUSTED_HOST` | （无） | 对应 trusted host。 |
| `HF_ENDPOINT` | （无） | HF 端点；`--mirror` 默认 `https://hf-mirror.com`。 |
| `FLASHCLI_GIT_PROXY` | （无） | GitHub 代理前缀；`--mirror` 默认 `https://gh-proxy.com/`；`0` 关闭。 |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | 优先 hf-mirror。 |

`~/.flashcli/mirror.env`（`--mirror` 写入）：`FLASHCLI_USE_MIRROR=1`、`PIP_INDEX_URL`、
`PIP_TRUSTED_HOST`、`HF_ENDPOINT`、`FLASHCLI_PREFER_HF_MIRROR=1`、`FLASHCLI_GIT_PROXY`。
镜像模式下 PyTorch wheel 走 `https://mirrors.aliyun.com/pytorch-wheels/<cu>/`（否则
`download.pytorch.org/whl`）。

安装器参数：`--mirror`/`--gitee`（并用 Gitee 源）、`--pip-mirror NAME`
（`tuna|aliyun|tencent|ustc|huawei|pypi`）、`--pip-probe`（PyPI 镜像测速）、
`--no-mirror`/`--global`（关闭）、`--github`（GitHub 源）。

## Bundle entry 环境变量（engine / script）

在**bundle venv infer 进程**内、entry 运行前注入。第三方 entry 只应依赖下列名字；其余 `FLASHCLI_*`
为内部值。

### Script 模式（`entry.*.mode: "script"`）

| 变量 | 必填 | 说明 |
|------|------|------|
| `FLASHCLI_CHECKPOINT` | 是 | 主权重目录（绝对路径，已校验）。 |
| `FLASHCLI_BUNDLE_ROOT` | 是 | bundle 根（绝对路径）。 |
| `FLASHCLI_PRESET` | 是 | preset ref 字符串。 |
| `FLASHCLI_VARIANT` | 否 | ref 含 `@variant` 时设置。 |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | 否 | 每个 manifest `extra_weights` key 一个（大写；非字母数字→`_`）。 |

### Engine 模式（默认）

| 来源 | 说明 |
|------|------|
| manifest **`env`** / variant **`env`** | entry 运行前应用；展开 `{bundle_root}`、`{models_dir}`。 |
| **`post_pull`** | 如 `FLASH_RT_PALIGEMMA_TOKENIZER`。 |
| **`--mtp-checkpoint`** | 设置 `FLASHRT_QWEN36_MTP_CKPT_DIR`。 |

engine 模式**不**设置 `FLASHCLI_CHECKPOINT`（权重经 `RunEngine.load(...)` 传入）。

## Infer / serve（bundle venv）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_HUB_OFFLINE` | `1`（host 设置） | 推理期禁止 Hub 网络访问。 |
| `TRANSFORMERS_OFFLINE` | `1`（host 设置） | 同上（`transformers`）。 |
| `HF_DATASETS_OFFLINE` | `1`（host 设置） | 同上（`datasets`）。 |
| `FLASHCLI_SERVE_LOG_LEVEL` | `INFO` | `flashcli serve` 应用日志级别。 |
| `FLASHCLI_UVICORN_LOG_LEVEL` | `info` | Uvicorn 日志级别。 |
| `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` | `0` | 引擎忙时最大等待秒数（`0` = 无限）。 |

## 内部（entry 代码不要依赖）

| 变量 | 说明 |
|------|------|
| `FLASHCLI_RUNTIME_ID` | re-exec 时的 runtime id。 |
| `FLASHCLI_IN_BUNDLE_VENV` | infer 子进程内为 `1`。 |
| `FLASHCLI_BUNDLE_ROOT` | re-exec 时的 bundle 根。 |
| `VIRTUAL_ENV` | bundle venv（Python 标准）。 |
| `LD_LIBRARY_PATH` | 追加 venv 的 nvidia lib 目录（`cuda`）。 |

## 依赖分层（pip）

| 层级 | 安装位置 | 包 / 来源 |
|------|----------|-----------|
| Host CLI | PATH | Go 二进制（`go/`、`install.sh`） |
| Protocol | 构建/开发 + bundle venv | `flashcli-bundle`（`dependencies = []`） |
| Infer runtime | bundle venv | `flashcli-bundle[infer]` |
| Model stack | bundle venv | `flashcli-bundle.json` → `python_dependencies` |

Go host 不 import Python infer 代码。Bundle venv **禁止** `pip install flashcli`。

## 相关文档

- [README.zh-CN.md](../README.zh-CN.md) — 快速开始与缓存布局
- [architecture.zh-CN.md](architecture.zh-CN.md) — host / protocol / infer 流程
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) — 执行 backend（`entry.kind`）
