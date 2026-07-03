# flashcli

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**用于分发与运行 [FlashRT](https://github.com/flashrt-project/FlashRT) 推理的生产级 CLI。**

安装一次、记住 preset 名称即可：flashcli 按 GPU 解析原生 runtime、拉取版本化 **Model Bundle**、安装 Python 依赖、缓存 Hugging Face 权重，并执行 **`run`**（引擎推理）或 **`serve`**（OpenAI 兼容 HTTP），无需手工拼接 FlashRT、CUDA 线与 pip 矩阵。

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
flashcli run flashcli-bundle/pi05_libero:1.0.4
```

---

## 概述

| 层级 | 职责 |
|------|------|
| **flashcli** | 分发 CLI — preset ref 解析、bundle 拉取、环境探测、依赖、缓存、HTTP 网关 |
| **Model Bundle** | 按模型族发布的制品（`flashcli-bundle.json` + Python entry + 按 env 分包的 `runtime/`） |
| **FlashRT** | 编译进 bundle 的内核与前端；**不是** flashcli 的 pip 依赖 |

flashcli 刻意保持轻薄：**推理代码在 bundle 内**。CLI 从 FlashHub 拉取 bundle、preflight 匹配 `runtime` env、创建 bundle venv，再调用各 bundle 的 `RunEngine` / `ServeEngine`。

---

## 核心优势

- **一条命令到首 token** — `flashcli run <ref>` 串联依赖安装、FlashHub bundle sync、权重拉取与推理。
- **按环境分包下载** — 只拉本机 GPU/CUDA/Python 对应的 `runtime/<env-key>/`；`flashcli models envs` 查看本机 env key。
- **可复现发布** — 维护者构建 `dist/` 上传 FlashHub；用户使用固定 ref（如 `flashcli-bundle/pi05_libero:1.0.4`）。
- **OpenAI 兼容服务** — Qwen NVFP4 提供 `/v1/chat/completions`、流式、tools、会话复用（FlashRT `qwen36_agent`）。
- **运维友好** — serve 结构化日志、`/health` 含 `inference_busy`、GPU batch=1 忙时 503、`doctor` 预检。
- **镜像网络友好** — Gitee 安装脚本、pip/HF 镜像环境变量；受限网络有文档化 fallback。

---

## 支持范围

在 **[FlashHub](https://flashhub.top)** 浏览已发布的 bundle。下表为常用 preset；模型介绍与运行命令见各 bundle **README**。

| Ref | 任务 | GPU | CUDA 线 | Python | 能力 |
|-----|------|-----|---------|--------|------|
| [`flashcli-bundle/pi05_libero:1.0.4`](bundles/pi05_libero/README.zh-CN.md) | Pi0.5 LIBERO VLA | **SM89**、**SM120** | cu124（SM89）· cu130 | **3.12**（bundle venv） | `run` |
| [`flashcli-bundle/qwen_nvfp4:1.0.1@qwen3`](bundles/qwen_nvfp4/README.zh-CN.md) | Qwen3-8B NVFP4 对话 | **SM120** | **仅 cu130** | **3.12** | `run`, `serve` |
| [`flashcli-bundle/qwen_nvfp4:1.0.1@qwen36`](bundles/qwen_nvfp4/README.zh-CN.md) | Qwen3.6-27B NVFP4 + MTP | **SM120** | **仅 cu130** | **3.12** | `run`, `serve` |
| [`flashcli-bundle/qwen3_vl_nvfp4:1.0.0`](bundles/qwen3_vl_nvfp4/README.zh-CN.md) | Qwen3-VL-8B NVFP4 图文 | **SM120** | **仅 cu130** | **3.12** | `run`, `serve` |
| [`flashcli-bundle/groot_n16:1.0.0`](bundles/groot_n16/README.zh-CN.md) | GROOT N1.6 VLA | **SM120** | **仅 cu130** | **3.12** | `run` |
| [`flashcli-bundle/groot_n17:1.0.0`](bundles/groot_n17/README.zh-CN.md) | GROOT N1.7 VLA | **SM120** | **仅 cu130** | **3.10** | `run` |

完整索引：[bundles/README.zh-CN.md](bundles/README.zh-CN.md)。已发布 ref：[FlashHub](https://flashhub.top)。

**平台要求**

- Linux x86_64，NVIDIA 驱动与 `nvidia-smi` 可用
- **容器**：NVIDIA CUDA 运行时镜像（Qwen SM120 推荐 `nvcr.io/nvidia/pytorch:25.10-py3`），勿用纯 `python:3.x`
- **网络**：首次需 FlashHub bundle sync + Hugging Face 权重（Pi0.5 另需 Google Storage 拉 PaliGemma tokenizer）

Qwen3 与 Qwen3.6 **共用** 同一 FlashHub repo；ref 中 `@qwen3` / `@qwen36` 区分权重。权重**不打进** bundle，缓存在 `~/.flashcli/models/<bundle>/<version>@<variant>/`。

---

## 更新动态

| 月份 | 亮点 |
|------|------|
| **2026-06** | **Qwen3.6 对话服务**达到生产可用 — 回复更快（遇结束符即停）、真流式输出、更长单次生成，HTTP 与推理安装更省心 |
| **2026-05** | **Blackwell（SM120）Qwen NVFP4** 上架 FlashHub — 一条命令 `run` / OpenAI 兼容 `serve`；可复现的多环境发布包 |

完整历史见 `git log`。

---

## 快速开始

### 1. 安装

**自动（推荐）**

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
```

**Github**

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
```

**源码（开发者）**

```bash
git clone https://github.com/aodianyun/flashcli.git && cd flashcli
pip install -e ./flashcli-bundle -e .
```

### 2. 预检

```bash
flashcli doctor
flashcli models list
flashcli models envs flashcli-bundle/pi05_libero:1.0.4
```

### 3. 首次推理 — 机器人（Pi0.5）

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

首次运行会 sync FlashHub runtime、创建 bundle venv、安装 torch 栈并拉取约 7.5GB 权重。

### 4. 大模型 — Qwen NVFP4

**引擎（无 HTTP）**

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --prompt "你好" --max-tokens 128
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --prompt "你好" --max-tokens 128 --K 6
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg --prompt "描述这张图" --max-tokens 128
```

**OpenAI 兼容服务**

```bash
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 --warmup-preset auto

flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 --warmup-preset auto

# qwen3-vl — 多模态（图 + 文）
flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 --host 0.0.0.0 --port 8000 \
  --max-pixels 500000 --warmup-preset short
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen36","messages":[{"role":"user","content":"你好"}],
       "max_tokens":512,"stream":true,"temperature":0}'
```

**本地 dev bundle**（FlashRT 编译，非 FlashHub）：

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve bundles/qwen_nvfp4@qwen36 --port 8000 --K 6 --max-seq 262208
```

各 bundle 文档：**[pi05_libero](bundles/pi05_libero/README.zh-CN.md)** · **[qwen_nvfp4](bundles/qwen_nvfp4/README.zh-CN.md)** · **[qwen3_vl_nvfp4](bundles/qwen3_vl_nvfp4/README.zh-CN.md)** · **[groot_n16](bundles/groot_n16/README.zh-CN.md)** · **[groot_n17](bundles/groot_n17/README.zh-CN.md)**。维护者构建见 [bundles/README.zh-CN.md](bundles/README.zh-CN.md)。

---

## CLI 速查

| 命令 | 用途 |
|------|------|
| `flashcli run <ref>` | 同步推理（VLA、对话等） |
| `flashcli serve <ref>` | OpenAI HTTP（Qwen） |
| `flashcli pull <ref>` | 预拉 runtime + 权重（与首次 `run` 相同的下载路径） |
| `flashcli models list` | 本地已缓存 ref 与权重状态（在 [FlashHub](https://flashhub.top) 发现 bundle） |
| `flashcli models envs [ref]` | 矩阵档位 vs 本机 GPU |
| `flashcli doctor [--install]` | 环境 / GPU 预检 |
| `flashcli bundle sync <ref>` | 从 FlashHub 预拉 bundle runtime |
| `flashcli bundle validate PATH` | 布局与 native 矩阵校验 |

**常用参数**：`--no-auto-install`、`--checkpoint`、`--quiet`  
**Ref 语法**：FlashHub `flashcli-bundle/name:version[@variant]` 或本地 `bundles/name[@variant]`（目录须含 `flashcli-bundle.json`）。多 variant bundle 必须带 `@variant`。详见 [model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md)。

Qwen `serve` 要点：`--max-seq`、`--max-q-seq`（qwen3）、`--K`、`--max-output-tokens`（默认 16384）、`--warmup-preset`、`--default-max-tokens`。

---

## 工作原理

```text
主机：install.sh → ~/.flashcli/venv（flashcli 只装一次）
  pull / run 预检 → 主机 Python（sync、权重、extra_weights、post_pull）

run/serve：
  ref → FlashHub → manifest + preflight → runtime/<env-key>/
  → 主机 ensure 权重（缺失则下载，与 pull 相同）
  → bundle venv（python_abi、torch…）
  → re-exec：bundle python -m flashcli_bundle.infer（HF hub 离线）
  → activate bundle → 本地 checkpoint → RunEngine / ServeEngine / script main
```

**不要**在 bundle venv 里 pip 安装 flashcli。详见 [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md#主机-cli-与-bundle-infer必读)。

**本机缓存**

| 路径 | 内容 |
|------|------|
| `~/.flashcli/venv/` | 主机 CLI（flashcli 唯一安装位置） |
| `~/.flashcli/runtimes/<id>/` | sync 后的 bundle 根（`runtime/<env-key>/`、entry 树）、bundle venv |
| `~/.flashcli/models/<bundle>/<version>@<variant>/checkpoint/` | 模型权重 |
| `~/.cache/flash_rt/` | Pi0.5 PaliGemma tokenizer |

环境变量：[docs/environment.zh-CN.md](docs/environment.zh-CN.md)。

---

## 文档

| 角色 | 阅读顺序 |
|------|----------|
| **终端用户** | 本 README → bundle [README](bundles/pi05_libero/README.zh-CN.md) → [environment.zh-CN.md](docs/environment.zh-CN.md) |
| **集成方** | [FlashHub](https://flashhub.top) → [model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md) — preset ref 语法 |
| **Bundle 作者** | [bundle_publish_standard.zh-CN.md](docs/bundle_publish_standard.zh-CN.md) → [flashcli-bundle/README.md](flashcli-bundle/README.md) |

主机 CLI、bundle venv、FlashHub sync 原理：[architecture.zh-CN.md](docs/architecture.zh-CN.md)。完整索引：[docs/README.zh-CN.md](docs/README.zh-CN.md)。

---

## 贡献与许可

欢迎贡献 — 见 [CONTRIBUTING.md](CONTRIBUTING.md)。

**许可证**：Apache-2.0（[`pyproject.toml`](pyproject.toml)）
