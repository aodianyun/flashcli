# flashcli 模块分层

<p align="right"><a href="module_layers.md">English</a> · <strong>简体中文</strong></p>

三层运行时共享一个协议包（`flashcli-bundle`）。本文是**模块放哪**的判定清单与 import 规则。

## 模块归属判定（核心）

**先问谁 import，再决定放哪：**

| 使用情况 | 放哪里 | 不要放 |
|----------|--------|--------|
| **只有** `flashcli`（host）用到 | `src/flashcli/` | `flashcli_bundle/` |
| **只有** `flashcli_bundle.infer` 用到 | `flashcli_bundle/infer/` | `flashcli_bundle/` 协议根 |
| **host 与 infer 都用** | `flashcli_bundle/`（protocol） | 拆成两份拷贝 |

```text
仅 host  → src/flashcli/
仅 infer → flashcli_bundle/infer/
两者都用 → flashcli_bundle/（protocol，dependencies = []）
```

**Protocol 不应包含（即使零 pip 依赖也算越界）：**

- Host 专有：Hugging Face 权重下载、`huggingface_hub`、GitHub release 下载、standalone Python 安装/探测、FlashHub sync 组装、re-exec
- Infer 专有：FastAPI/uvicorn、engine loader、HTTP serve 栈、bundle venv 内 Typer 入口

**允许在 protocol 的「共享编排」**（host/infer 各注入依赖，不 duplicate）：

- `activate_core.py` — pip/venv 通过回调注入
- `cache.py` / `weights.py` — resolve 共享；HF **下载实现**应在 host
- `post_pull.py` — run/pull 后 host 与 infer 都可能触发

**Re-export 不是放 protocol 的理由：** host/infer 的薄 re-export 仅为稳定 import 路径；若逻辑只在一层使用，应直接放在该层。

**Host 专有模块示例**（非穷举）：`python_paths.py`、`python_resolve.py`、`runtime/mirror_github.py`、`bundle/weights.py`（HF 下载）、`models/hf_hub.py`、`models/pull.py`、`bundle/artifacts.py`、`runtime/reexec.py`。

## 分层概览

| 层 | pip 安装 | 可 import | 禁止 |
|----|----------|-----------|------|
| **Protocol** | `flashcli-bundle`（`dependencies = []`） | `flashcli_bundle.*`（除 `infer`） | `flashcli`、fastapi/uvicorn/torch、`flashcli_bundle.infer` |
| **Host** | `flashcli` + `flashcli-bundle` | `flashcli.*`、`flashcli_bundle.*` | `flashcli_bundle.infer` |
| **Infer** | `flashcli-bundle[infer]` + manifest deps | `flashcli_bundle.*`（含 `infer`） | `flashcli`、`huggingface_hub` |

```text
Host venv:     flashcli ──► flashcli_bundle (protocol)
Bundle venv:   flashcli_bundle.infer ──► flashcli_bundle (protocol + [infer] extra)
```

Host 与 infer **不得**相互 import。

##  enforcement

结构规则见 `tests/test_architecture_layers.py`：

- Host 不 import `flashcli_bundle.infer`
- Protocol `dependencies = []`
- Infer extra 含 serve 栈、不含 `huggingface_hub`
- `HOST_ONLY_PROTOCOL_MODULES` 白名单不得扩大
- Infer `runtime/mirror` 不得 re-export GitHub release 下载 API
- Infer 不得 import `flashcli`；protocol 不得 import `huggingface_hub`
- 过时兼容 shim（如 `infer/config.py`、`bundle/standalone_release.py`）不得恢复

详见 [architecture.zh-CN.md](architecture.zh-CN.md)。
