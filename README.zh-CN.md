# flashcli

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**面向 NVIDIA GPU 的 [FlashRT](https://github.com/flashrt-ai/FlashRT) 推理分发 CLI。**

安装一次、记住 preset 名称即可：flashcli 按 GPU 解析原生 runtime、拉取版本化 **Model Bundle**、安装 Python 依赖、缓存 Hugging Face 权重，并执行 **`run`**（引擎推理）或 **`serve`**（OpenAI 兼容 HTTP），无需手工拼接 FlashRT、CUDA 线与 pip 矩阵。

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
flashcli run pi05_libero --prompt "pick up the red block" --image /path/to/scene.jpg
```

---

## 概述

| 层级 | 职责 |
|------|------|
| **flashcli** | 分发 CLI — catalog、bundle 拉取、环境探测、依赖、缓存、HTTP 网关 |
| **Model Bundle** | 按模型族发布的制品（`flashcli-bundle.json` + `lib/*.so` + Python entry） |
| **FlashRT** | 编译进 bundle 的内核与前端；**不是** flashcli 的 pip 依赖 |

flashcli 刻意保持轻薄：**推理代码在 bundle 内**。CLI 将 bundle 加入 `PYTHONPATH`、从 native 矩阵（`sm*-cu*-linux-x86_64-py*`）选取匹配 `.so`，再调用各 bundle 的 `RunEngine` / `ServeEngine`。

---

## 核心优势

- **一条命令到首 token** — `flashcli run <preset>` 串联依赖安装、CDN bundle、权重拉取与推理。
- **按环境选原生库** — 多 ABI zip（`lib/flash_rt_kernels-*-py310.so` 等），无需手工挑 `.so`；`flashcli models envs` 查看本机匹配档。
- **可复现发布** — 维护者打一次矩阵 zip，用户通过 [`models.yaml`](src/flashcli/catalog/models.yaml) 消费固定 CDN URL。
- **OpenAI 兼容服务** — Qwen NVFP4 提供 `/v1/chat/completions`、流式、tools、会话复用（FlashRT `qwen36_agent`）。
- **运维友好** — serve 结构化日志、`/health` 含 `inference_busy`、GPU batch=1 忙时 503、`doctor` 预检。
- **镜像网络友好** — Gitee 安装脚本、pip/HF 镜像环境变量；受限网络有文档化 fallback。

---

## 支持范围

| Preset | 任务 | GPU | CUDA 线 | Python | 能力 |
|--------|------|-----|---------|--------|------|
| [`pi05_libero`](bundles/pi05_libero/QUICKSTART.zh-CN.md) | Pi0.5 LIBERO VLA | **SM89** | cu124 或 cu130 | 3.10–3.12 | `run` |
| [`qwen3-8b-nvfp4`](bundles/qwen_nvfp4/QUICKSTART.zh-CN.md) | Qwen3-8B NVFP4 对话 | **SM120** | **仅 cu130** | 3.10–3.12 | `run`, `serve` |
| [`qwen36-27b-nvfp4`](bundles/qwen_nvfp4/QUICKSTART.zh-CN.md) | Qwen3.6-27B NVFP4 + MTP | **SM120** | **仅 cu130** | 3.10–3.12 | `run`, `serve` |

**平台要求**

- Linux x86_64，NVIDIA 驱动与 `nvidia-smi` 可用
- **容器**：NVIDIA CUDA 运行时镜像（Qwen SM120 推荐 `nvcr.io/nvidia/pytorch:25.10-py3`），勿用纯 `python:3.x`
- **网络**：首次需 CDN bundle zip + Hugging Face 权重（Pi0.5 另需 Google Storage 拉 PaliGemma tokenizer）

Qwen3 与 Qwen3.6 **共用** runtime zip；catalog 用 `bundle_variant` 区分权重。权重**不打进** zip，缓存在 `~/.flashcli/models/<preset>/`。

---

## 更新动态

| 月份 | 亮点 |
|------|------|
| **2026-06** | **Qwen3.6 对话服务**达到生产可用 — 回复更快（遇结束符即停）、真流式输出、更长单次生成，HTTP 与推理安装更省心 |
| **2026-05** | **Blackwell（SM120）Qwen NVFP4** 入库 — 一条命令 `run` / OpenAI 兼容 `serve`；可复现的多环境发布包 |

完整历史见 `git log`；发布 checklist：[CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 快速开始

### 1. 安装

**自动（推荐）**

```bash
curl -fsSL https://flashhub.top/flashcli_install/auto_install.sh | sh
```

**源码（开发者）**

```bash
git clone https://github.com/aodianyun/flashcli.git && cd flashcli
pip install -e .
```

### 2. 预检

```bash
flashcli doctor
flashcli models list
flashcli models envs pi05_libero
```

### 3. 首次推理 — 机器人（Pi0.5）

```bash
flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

首次运行会下载 runtime zip、安装 torch 栈并拉取约 7.5GB 权重。

### 4. 大模型 — Qwen NVFP4

**引擎（无 HTTP）**

```bash
flashcli run qwen3-8b-nvfp4 --prompt "你好" --max-tokens 128
flashcli run qwen36-27b-nvfp4 --prompt "你好" --max-tokens 128 --K 6
```

**OpenAI 兼容服务**

```bash
flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 --warmup-preset auto

flashcli serve qwen36-27b-nvfp4 --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 --warmup-preset auto
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-27b-nvfp4","messages":[{"role":"user","content":"你好"}],
       "max_tokens":512,"stream":true,"temperature":0}'
```

**本地 dev bundle**（FlashRT 编译，非 CDN）：

```bash
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve qwen36-27b-nvfp4 --bundle "$BUNDLE" --port 8000 --K 6 --max-seq 262208
```

分 bundle 详细步骤：**[qwen_nvfp4 快速上手](bundles/qwen_nvfp4/QUICKSTART.zh-CN.md)** · **[pi05_libero 快速上手](bundles/pi05_libero/QUICKSTART.zh-CN.md)**

---

## 模型目录

| Preset | 权重（Hugging Face） | Bundle 快速上手 |
|--------|----------------------|-----------------|
| `pi05_libero` | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) | [QUICKSTART](bundles/pi05_libero/QUICKSTART.zh-CN.md) |
| `qwen3-8b-nvfp4` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | [QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.zh-CN.md) |
| `qwen36-27b-nvfp4` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + [MTP](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) | [QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.zh-CN.md) |

Catalog 源文件：[`src/flashcli/catalog/models.yaml`](src/flashcli/catalog/models.yaml)。Bundle 规范：[docs/model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md)。

---

## CLI 速查

| 命令 | 用途 |
|------|------|
| `flashcli run <preset>` | 同步推理（VLA、对话等） |
| `flashcli serve <preset>` | OpenAI HTTP（Qwen） |
| `flashcli pull <preset>` | 仅预拉权重 |
| `flashcli models list` | Catalog 与本地缓存状态 |
| `flashcli models envs [preset]` | 矩阵档位 vs 本机 GPU |
| `flashcli doctor [--install]` | 环境 / GPU 预检 |
| `flashcli bundle sync <preset>` | 预拉 runtime zip |
| `flashcli bundle validate PATH` | 布局与 native 矩阵校验 |

**常用参数**：`--bundle PATH`、`--no-auto-install`、`--checkpoint`、`--quiet`

`flash` 与 `flashcli` 等价。

Qwen `serve` 要点：`--max-seq`、`--max-q-seq`（qwen3）、`--K`、`--max-output-tokens`（默认 16384）、`--warmup-preset`、`--default-max-tokens`。

---

## 工作原理

```text
models.yaml  →  bundle zip/path  →  activate（PYTHONPATH + lib/*.so）
              →  pip（torch…）     →  HF 权重缓存  →  RunEngine / ServeEngine
```

序列图与模块图：[docs/architecture.zh-CN.md](docs/architecture.zh-CN.md)。

**本机缓存**

| 路径 | 内容 |
|------|------|
| `~/.flashcli/bundles/<preset>/` | 解压后的 runtime zip |
| `~/.flashcli/models/<preset>/checkpoint/` | 模型权重 |
| `~/.cache/flash_rt/` | Pi0.5 PaliGemma tokenizer |

环境变量：[docs/environment.zh-CN.md](docs/environment.zh-CN.md)。

---

## 文档

| 文档 | 读者 |
|------|------|
| [docs/README.zh-CN.md](docs/README.zh-CN.md) | 文档索引 |
| [docs/environment.zh-CN.md](docs/environment.zh-CN.md) | 安装参数、环境变量、镜像 |
| [docs/runtime-matrix.zh-CN.md](docs/runtime-matrix.zh-CN.md) | Native 矩阵与发布构建 |
| [docs/model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md) | Bundle 规范 |
| [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md) | 模块与数据流 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献与发布 checklist |
| [FlashRT](https://github.com/flashrt-ai/FlashRT) | 内核与模型文档 |

---

## 贡献与许可

欢迎贡献 — 见 [CONTRIBUTING.md](CONTRIBUTING.md)。Bundle 维护者：`bash scripts/release_bundle.sh --bundle <name> --clean`。

**许可证**：Apache-2.0（[`pyproject.toml`](pyproject.toml)）
