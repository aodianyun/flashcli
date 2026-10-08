# flashcli 模块分层

<p align="right"><a href="module_layers.md">English</a> · <strong>简体中文</strong></p>

三层：**Go 主机** + 协议包（`flashcli-bundle`）+ infer。本文是**模块放哪**的判定清单与 import 规则。

## 模块归属判定（核心）

**先问谁 import，再决定放哪：**

| 使用情况 | 放哪里 | 不要放 |
|----------|--------|--------|
| **只有** `flashcli`（Go host）用到 | `go/internal/` | `flashcli_bundle/` |
| **只有** `flashcli_bundle.infer` 用到 | `flashcli_bundle/infer/` | `flashcli_bundle/` 协议根 |
| **host 与 infer 都用** | `flashcli_bundle/`（protocol） | 拆成两份拷贝 |

```text
仅 host  → go/internal/
仅 infer → flashcli_bundle/infer/
两者都用 → flashcli_bundle/（protocol，dependencies = []）
```

**Protocol 不应包含（即使零 pip 依赖也算越界）：**

- Host 专有：Hugging Face 权重下载、`huggingface_hub`、GitHub release 下载、standalone Python 安装/探测、FlashHub sync 组装、re-exec
- Infer 专有：FastAPI/uvicorn、engine loader、HTTP serve 栈、bundle venv 内 Typer 入口

**允许在 protocol 的「共享编排」**（host/infer 各注入依赖，不 duplicate）：

- `activate_core.py` — pip/venv 通过回调注入
- `cache.py` / `weights.py` — resolve 共享；HF **下载实现**与 `extra_weights` 按文件拉取在 host（`models/pull.py`）
- `post_pull.py` — run/pull 后 host 与 infer 都可能触发

**Re-export 不是放 protocol 的理由：** host/infer 的薄 re-export 仅为稳定 import 路径；若逻辑只在一层使用，应直接放在该层。

**Host 专有代码**位于 `go/internal/`（Go）。示例：`weights`（HF/ModelScope 下载、`post_pull`）、`flashhub`（sync）、`venv`/`pythonprovision`、`inferexec`/`nativeexec`/`nativeabi`、`cli`。

## 分层概览

| 层 | 语言 / 安装 | 可 import | 禁止 |
|----|-------------|-----------|------|
| **Protocol** | Python `flashcli-bundle`（`dependencies = []`） | `flashcli_bundle.*`（除 `infer`） | fastapi/uvicorn/torch、`flashcli_bundle.infer` |
| **Host** | Go 二进制（`go/`） | 执行边界上的 `flashcli_bundle.*`（protocol） | `flashcli_bundle.infer` |
| **Infer** | Python `flashcli-bundle[infer]` + manifest deps | `flashcli_bundle.*`（含 `infer`） | `huggingface_hub`（权重下载） |

```text
Host (Go) ──re-exec/exec──► flashcli_bundle.infer ──► flashcli_bundle (protocol + [infer])
```

Go 主机**不** import Python infer 包；它以子进程启动（或驱动原生 backend）。

## Enforcement

- **Protocol** `flashcli-bundle/pyproject.toml` 保持 `dependencies = []`；infer extra 含 serve 栈、不含 `huggingface_hub`。
- **执行 ABI / host 对等**由 `tests/conformance/` 强制（命令面对等、Py↔Go execution ABI 一致、re-exec/原生 backend）。
- **Go host** 由 `go test ./...` 覆盖。
- Python host（`src/flashcli/`）已移除；不要重新把 host 专有代码放回 `flashcli_bundle/`。

详见 [architecture.zh-CN.md](architecture.zh-CN.md)。
