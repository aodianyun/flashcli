# flashcli

[FlashRT](https://github.com/flashrt-ai/FlashRT) 的**分发 CLI**：一条命令拉取 Model Bundle、安装运行时依赖、下载权重并执行推理。

## 要求

- **Linux** + **NVIDIA GPU**（已验证：**SM89**，如 RTX 4090 / L40；bundle 元数据亦声明支持 SM120）
- **Python** 3.10–3.12
- 网络：首次运行会从 CDN 拉取 runtime zip，从 Hugging Face 拉取模型权重；Pi0.5 还需 Google Storage（PaliGemma tokenizer）

## 快速开始

```bash
pip install flashcli
# 开发：cd flashcli && pip install -e .

flashcli doctor
flashcli models list

flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

首次 `run` 会自动：安装 CLI 依赖 → 下载并解压 **runtime bundle**（zip）→ 按 `runtime/manifest.json` 安装 torch 等 → 下载 HF 权重 → `post_pull`（PaliGemma tokenizer）→ 加载 `partner.run.RunEngine` 推理。

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

| Preset | 能力 | Runtime 来源 | 权重 |
|--------|------|--------------|------|
| `pi05_libero` | `run` | CDN zip（`models.yaml` → `bundle.zip`） | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) |

`models.yaml` 只登记 **preset 名** 与 **bundle 源**；`weights`、`entry`、`defaults` 等见各包内的 [`flashcli-bundle.json`](docs/model_bundle_standard.md)。

## 本机缓存

| 路径 | 内容 |
|------|------|
| `~/.flashcli/bundles/<preset>/` | 已下载的 runtime zip 解压目录 |
| `~/.flashcli/models/<preset>/checkpoint/` | Hugging Face 权重 |
| `~/.cache/flash_rt/` | PaliGemma tokenizer（`post_pull`） |

## 环境变量

| 变量 | 说明 |
|------|------|
| `FLASHCLI_HOME` | 缓存根目录，默认 `~/.flashcli` |
| `FLASHCLI_SKIP_AUTO_INSTALL=1` | 不自动 pip 安装 manifest 依赖 |
| `FLASH_RT_PALIGEMMA_TOKENIZER` | 指定 PaliGemma tokenizer 文件路径 |

## 命令

| 命令 | 说明 |
|------|------|
| `flashcli run <preset>` | VLA 等批推理（`pi05_libero` 使用此命令） |
| `flashcli pull <preset>` | 仅预拉权重 |
| `flashcli models list` | 查看 catalog |
| `flashcli doctor` | 环境与 GPU 检查 |
| `flashcli bundle validate PATH` | 校验本地 bundle 布局 |
| `--bundle PATH` | 覆盖 catalog，使用本地 bundle 根目录 |

`flashcli serve` 用于带 HTTP 的 LLM bundle；**`pi05_libero` 仅支持 `run`**。

`flash` 与 `flashcli` 为同一入口（`pyproject.toml` 中均注册）。

## 文档

| 文档 | 读者 |
|------|------|
| [docs/model_bundle_standard.md](docs/model_bundle_standard.md) | Model Bundle 格式（扩展方 / 维护者） |
| [docs/architecture.md](docs/architecture.md) | 模块划分与数据流 |

推理内核与精度说明请参阅 [FlashRT](https://github.com/flashrt-ai/FlashRT) 仓库文档。

## 许可证

Apache-2.0（见 `pyproject.toml`）。
