# 环境变量

<p align="right"><a href="environment.md">English</a> · <strong>简体中文</strong></p>

flashcli 通过环境变量配置缓存路径、catalog、下载行为，以及与 Hugging Face / 特定 preset 的集成。未列出的变量对 flashcli **无效果**。

取值约定：`1` / `true` / `yes`（不区分大小写）视为开启布尔开关。

## 路径与 catalog

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_HOME` | `~/.flashcli` | 缓存根目录。其下默认有 `bundles/`、`models/`、`cache/downloads/`。 |
| `FLASHCLI_BUNDLES_DIR` | `$FLASHCLI_HOME/bundles` | 覆盖 runtime bundle（zip/git）缓存目录。 |
| `FLASHCLI_MODELS_DIR` | `$FLASHCLI_HOME/models` | 覆盖 Hugging Face 权重缓存根目录（各 preset 一般为 `<dir>/<preset>/checkpoint/`）。 |
| `FLASHCLI_MODELS_YAML` | （内置） | **覆盖 preset catalog 文件路径**。默认使用安装包内 `flashcli/catalog/models.yaml`（pip wheel 与 editable 相同）。指向的文件必须存在。 |

维护 catalog 时通常**直接改**仓库内 [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)；仅在多版本并存、CI 或容器内挂载自定义 catalog 时设置 `FLASHCLI_MODELS_YAML`。

示例：

```bash
export FLASHCLI_HOME=/data/flashcli
export FLASHCLI_MODELS_YAML=/etc/flashcli/models.yaml
flashcli models list
```

## 下载与 Hugging Face

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HF_ENDPOINT` | （官方 Hub） | **官方镜像开关**（与 `hf download` / `huggingface-cli download` 相同）。例：`https://hf-mirror.com`。设置后 flashcli 只走该端点。 |
| （自动） | — | 未设置 `HF_ENDPOINT` 时：先试官方 Hub，失败再试镜像（内部调用 `hf download`）。 |
| `FLASHCLI_PREFER_HF_MIRROR` | `0` | 设为 `1` 时改为先镜像、再官方 Hub。 |
| `HF_TOKEN` | （无） | Hugging Face 访问令牌；gated 模型需 `hf auth login` 或设置此变量。 |
| `HF_HUB_ETAG_TIMEOUT` | `5` | Hub CLI：元数据/HEAD 超时（秒）；未设时 flashcli 默认 5。 |
| `HF_HUB_DOWNLOAD_TIMEOUT` | `5` | Hub CLI：单次 HTTP 超时（秒）；未设时 flashcli 默认 5。 |
| `FLASHCLI_HF_ETAG_TIMEOUT` | `5` | 仅当未设置 `HF_HUB_ETAG_TIMEOUT` 时生效。 |
| `FLASHCLI_HF_DOWNLOAD_TIMEOUT` | `5` | 仅当未设置 `HF_HUB_DOWNLOAD_TIMEOUT` 时生效。 |
| `FLASHCLI_HF_PROBE_TIMEOUT` | `3` | 探测官方 Hub 是否可达（秒）；不可达则跳过官方、直接镜像。 |
| `FLASHCLI_SKIP_HF_PROBE` | `0` | 设为 `1` 时不做探测，仍先试官方（`hf` 内部会慢重试）。 |

权重下载与 `hf download` 相同；失败时请先用相同 `HF_ENDPOINT` 手动试一次 CLI。

`install.sh` / `pip install flashcli` 会安装 `huggingface_hub>=0.26`（提供 `hf` / `huggingface-cli`），安装后校验 Hub CLI；若脚本目录不在 PATH，flashcli 仍会回退到 `python -m huggingface_hub.cli.hf`。

## 行为开关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASHCLI_SKIP_AUTO_INSTALL` | `0` | 设为 `1` 时，`flashcli run` / `serve` / `pull` **不**自动 pip 安装 flashcli 自身依赖（typer、huggingface_hub 等）。等价于命令行 `--no-auto-install`。 |
| `FLASHCLI_SKIP_BUNDLE_ZIP` | `0` | 设为 `1` 时，**禁止**从 `models.yaml` 下载/解压 `bundle.zip`；若本地无缓存则报错。用于离线或仅使用 `--bundle` 本地目录。 |
| `FLASHCLI_SKIP_BUNDLE_GIT` | `0` | 设为 `1` 时，**禁止** `git clone`/`fetch` bundle 仓库；若本地无缓存则报错。 |

Bundle 的 Python 依赖（torch 等）由 `activate_bundle` 按 `flashcli-bundle.json` 的 `python_dependencies` 安装；与 `FLASHCLI_SKIP_AUTO_INSTALL` 无关（后者只影响 flashcli CLI 包依赖）。

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
| `PYTHONPATH` | 在原有值之前** prepend** bundle 根目录，以便 `import` entry 与 `flash_rt`。 |

## 相关文档

- [README.zh-CN.md](../README.zh-CN.md) — 快速开始与本机缓存路径
- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — catalog 与 `flashcli-bundle.json`
- [src/flashcli/catalog/models.yaml](../src/flashcli/catalog/models.yaml) — preset catalog 唯一源文件
