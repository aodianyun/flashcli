# flashcli

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

[FlashRT](https://github.com/flashrt-ai/FlashRT) 的**分发 CLI**：一条命令拉取 Model Bundle、安装运行时依赖、下载权重并执行推理。

## 要求

- **Linux** + **NVIDIA GPU**（**SM89**：Pi0.5；**SM120**：Qwen NVFP4，如 RTX PRO 5000 Blackwell）
- **Python ≥ 3.10**（见 [`pyproject.toml`](pyproject.toml)）；`install.sh` 会安装 **flashcli** 与 **`huggingface_hub`**（提供 `hf download` / `huggingface-cli download`）
- **网络**：首次运行从 CDN 拉 runtime zip；权重经 Hub CLI 下载（与 `HF_ENDPOINT` + `hf download` 相同）。国内/内网建议 `export HF_ENDPOINT=https://hf-mirror.com`。Pi0.5 还需 Google Storage（PaliGemma tokenizer）

## 快速开始

一键安装（检测 Linux / NVIDIA GPU / Python 3.10+ / git，再通过 pip 安装）：

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
# 受限网络（镜像 PyPI + HF）：
# curl -fsSL …/install.sh | sh -s -- --mirror
# 指定分支 / 源码地址（如 Gitee）：
# curl -fsSL …/install.sh | sh -s -- --repo https://gitee.com/your-org/flashcli.git --ref main
```

也可将 `install.sh` 托管为 `https://your-domain/install` 后执行 `curl -fsSL https://your-domain/install | sh`。`--mirror` 使用备用 PyPI 与 Hub 镜像；`--repo` / `--git-url` 指定任意 Git 远程（GitHub、Gitee 等）；默认仍从 `main` @ GitHub 安装。脚本会**优先选用已带 pip 的 Python**；`run` 时按 GPU + **Python 3.10/3.11/3.12** 选择 runtime zip（见 [docs/runtime-matrix.zh-CN.md](docs/runtime-matrix.zh-CN.md)）（例如 Docker 里 `/usr/local/bin/python3.12`，而不是 Debian 的 PEP 668 `python3.13`），并处理 `ensurepip` / `get-pip.py` / `apt python3-pip` / 专用 venv。可选：`FLASHCLI_PYTHON=$(command -v python3)`、`FLASHCLI_USE_VENV=1`、`FLASHCLI_BREAK_SYSTEM_PACKAGES=1`、`FLASHCLI_AUTO_INSTALL_PYTHON=1`。**root** 默认系统级安装到 `/usr/local/bin`。

或手动安装：

```bash
pip install git+https://github.com/aodianyun/flashcli.git
# pip install --force-reinstall git+https://github.com/aodianyun/flashcli.git

flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

首次 `run` 会自动：安装 CLI 依赖 → 按本机 GPU 环境解析 `models.yaml` 中的 bundle 源并下载/解压 → 按 `flashcli-bundle.json` 的 `python_dependencies` 安装 torch 等 → 下载 HF 权重 → `post_pull`（PaliGemma tokenizer）→ 加载 bundle `entry`（如 `run.RunEngine`）推理。

预拉权重（可选）：

```bash
flashcli pull pi05_libero
```

调试本地已组装的 bundle：

```bash
flashcli run pi05_libero \
  --bundle /path/to/bundle \
  --checkpoint /path/to/ckpt \
  --image /path/to/base.jpg
```

## 当前 catalog

| Preset | 能力 | Runtime | 权重 |
|--------|------|---------|------|
| `pi05_libero` | `run` | CDN zip（SM89 × cu124/cu130 × py310/311/312） | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) |
| `qwen3-8b-nvfp4` | `run`, `serve` | 与 qwen36 **同一** CDN zip（SM120 × cu130 × py310/311/312） | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) |
| `qwen36-27b-nvfp4` | `run`, `serve` | 同上 | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + MTP |

`models.yaml` 只登记 **preset** 与 **bundle 源**（`zip`/`path`）；`bundle_variant` 区分共享 runtime 下的权重。详见 [`flashcli-bundle.json`](docs/model_bundle_standard.zh-CN.md)。

查看本机匹配的环境：

```bash
flashcli models envs pi05_libero
```

## 本机缓存

| 路径 | 内容 |
|------|------|
| `~/.flashcli/bundles/<preset>/` | 已下载的 runtime zip 解压目录 |
| `~/.flashcli/models/<preset>/checkpoint/` | Hugging Face 权重 |
| `~/.cache/flash_rt/` | PaliGemma tokenizer（`post_pull`） |

## 环境变量

常用变量（完整说明见 **[docs/environment.zh-CN.md](docs/environment.zh-CN.md)**）：

| 变量 | 说明 |
|------|------|
| `FLASHCLI_HOME` | 缓存根目录，默认 `~/.flashcli` |
| `FLASHCLI_BUNDLES_DIR` | 覆盖 bundle 缓存目录（默认 `$FLASHCLI_HOME/bundles`） |
| `FLASHCLI_MODELS_DIR` | 覆盖 HF 权重缓存目录（默认 `$FLASHCLI_HOME/models`） |
| `FLASHCLI_MODELS_YAML` | 覆盖 preset catalog 路径（默认包内 `flashcli/catalog/models.yaml`） |
| `FLASHCLI_SKIP_AUTO_INSTALL=1` | 不自动 pip 安装 flashcli CLI 依赖（同 `--no-auto-install`） |
| `FLASHCLI_SKIP_BUNDLE_ZIP=1` | 禁止下载 catalog 中的 `bundle.zip` |
| `FLASHCLI_SKIP_BUNDLE_GIT=1` | 禁止 git 拉取 bundle |
| `HF_ENDPOINT` | Hugging Face 镜像（如 `https://hf-mirror.com`）；未设置时默认先试官方 Hub，失败再试镜像 |
| `HF_TOKEN` | Hugging Face 令牌（gated 模型；由 `huggingface_hub` 使用） |
| `FLASH_RT_PALIGEMMA_TOKENIZER` | Pi0.5 PaliGemma tokenizer 文件路径 |
| `FLASHRT_QWEN36_MTP_CKPT_DIR` | Qwen3.6 MTP 权重目录（或由 `--mtp-checkpoint` 设置） |

## 命令

| 命令 | 说明 |
|------|------|
| `flashcli run <preset>` | 推理（Pi0.5 VLA、Qwen 对话等） |
| `flashcli serve <preset>` | OpenAI 兼容 HTTP（Qwen NVFP4） |
| `flashcli pull <preset>` | 仅预拉权重 |
| `flashcli models list` | 查看 catalog 与缓存状态 |
| `flashcli models envs [preset]` | 查看 `models.yaml` 中的环境与当前 GPU 匹配项 |
| `flashcli doctor` | 环境与 GPU 检查 |
| `flashcli bundle sync <preset>` | 预拉取/更新 runtime bundle |
| `flashcli bundle validate PATH` | 校验布局、`lib/` 矩阵是否齐全、各 `.so` 是否可用对应 `python3.x` 加载（`--skip-abi-probe` 仅查矩阵） |
| `--bundle PATH` | 覆盖 catalog，使用本地 bundle 根目录 |

**`pi05_libero` 仅支持 `run`**；Qwen preset 支持 `run` 与 `serve`。

`flash` 与 `flashcli` 为同一入口（`pyproject.toml` 中均注册）。

## 文档

完整索引（含 English）：[docs/README.zh-CN.md](docs/README.zh-CN.md)

| 文档 | 读者 |
|------|------|
| [docs/environment.zh-CN.md](docs/environment.zh-CN.md) | 环境变量完整说明 |
| [docs/model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md) | Model Bundle 格式（扩展方 / 维护者） |
| [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md) | 模块划分与数据流 |

推理内核与精度说明请参阅 [FlashRT](https://github.com/flashrt-ai/FlashRT) 仓库文档。

## 许可证

Apache-2.0（见 `pyproject.toml`）。
