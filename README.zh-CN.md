# flashcli

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**用于分发与运行 [FlashRT](https://github.com/flashrt-project/FlashRT) 推理的生产级 CLI。**

安装一次、记住 preset 名称即可：flashcli 按 GPU 解析原生 runtime、从 FlashHub 拉取版本化 **Model Bundle**、安装其 Python 依赖、缓存权重，并执行 **`run`**（推理）或 **`serve`**（OpenAI 兼容 HTTP），无需手工拼接 FlashRT、CUDA 线与 pip 矩阵。

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
flashcli doctor
flashcli run flashcli-bundle/<name>:<version>[@variant]
```

---

## Bundle

所有支持的模型与硬件都在 **[FlashHub](https://flashhub.top)** 上——去那里浏览，并使用各 bundle 页面给出的 ref。GPU/CUDA/Python 要求、能力，以及 `run` / `serve` 的命令与选项，都记录在该 bundle 页面及其 `README.md`（索引：[bundles/](bundles/README.zh-CN.md)）。

Ref 语法：`flashcli-bundle/<name>:<version>[@variant]`（FlashHub）或 `bundles/<name>[@variant]`（本地开发；目录须含 `flashcli-bundle.json`）。多 variant bundle 需要 `@variant`。详见 [model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md)。完整命令列表见 `flashcli --help`。

---

## 更新动态

| 月份 | 亮点 |
|------|------|
| **2026-10** | **Go-only host** —— 单个静态二进制（Python host 已移除）；**native-exec** / **native-abi** 后端让 bundle **无需 Python** 即可运行；同步的 bundle 树与权重缓存**在 `@variant` 间共享** |
| **2026-06** | **Qwen3.6 对话服务**达到生产可用 —— 回复更快（遇结束符即停）、真流式输出、更长单次生成，HTTP 与推理安装更省心 |
| **2026-05** | **Blackwell（SM120）Qwen NVFP4** 上架 FlashHub —— 一条命令 `run` / OpenAI 兼容 `serve`；可复现的多环境发布包 |

完整历史见 `git log`。

---

## 快速开始

### 安装 host（`flashcli`）

**一键（推荐）**

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
# 国内镜像：curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
```

`install.sh` 安装 `flashcli` 二进制：默认从最新 release 下载
`flashcli-<os>-<arch>` + `sha256sums.txt`（无需 Go），校验 sha256，并写入
`~/.flashcli/install.env`。加 `--from-source` 则改为 clone 后用 Go 构建。缺失的系统工具
（curl/wget、sha256、git）在 root 下会经系统包管理器自动安装。

**自动（按可达性选 GitHub/Gitee）**

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
```

**源码构建（开发）**

```bash
git clone https://github.com/aodianyun/flashcli.git && cd flashcli
bash scripts/build_go.sh        # 构建 go/ → dist/go/flashcli-<os>-<arch>
```

host 是静态 Go 二进制（无 Python host）。bundle venv 仍按需安装
`flashcli-bundle[infer]`（源码：[flashcli-bundle/](flashcli-bundle/)）。

### 预检

```bash
flashcli doctor
flashcli models envs flashcli-bundle/<name>:<version>   # 本机 GPU 对应的 native 矩阵
```

### 运行与服务

```bash
flashcli run   flashcli-bundle/<name>:<version>[@variant] [OPTIONS]        # 推理
flashcli serve flashcli-bundle/<name>:<version>[@variant] --port 8000      # OpenAI 兼容 HTTP

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<variant>","messages":[{"role":"user","content":"Hello"}],"max_tokens":512,"stream":true}'
```

首次运行会同步 FlashHub runtime、创建 bundle venv、安装 torch 栈并拉取权重。各模型的专属参数、默认值与示例见各 bundle [README](bundles/README.zh-CN.md)。

**本地开发 bundle**（从 FlashRT 重建，非 FlashHub）：

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve bundles/qwen_nvfp4@qwen36 --port 8000 --K 6
```

---

## 文档

| 角色 | 阅读顺序 |
|------|----------|
| **终端用户** | 本 README（安装 + 运行）→ bundle [README](bundles/README.zh-CN.md) → [environment.zh-CN.md](docs/environment.zh-CN.md) |
| **集成方** | [FlashHub](https://flashhub.top) → [model_bundle_standard.zh-CN.md](docs/model_bundle_standard.zh-CN.md) —— preset ref 语法 |
| **Bundle 作者** | [bundle_publish_standard.zh-CN.md](docs/bundle_publish_standard.zh-CN.md) → [flashcli-bundle/README.md](flashcli-bundle/README.md) |

host、bundle venv 与 FlashHub 同步的工作方式：[architecture.zh-CN.md](docs/architecture.zh-CN.md)。完整索引：[docs/README.zh-CN.md](docs/README.zh-CN.md)。

---

## 贡献与许可

欢迎贡献 —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。

**License**：Apache-2.0（[`pyproject.toml`](pyproject.toml)）
