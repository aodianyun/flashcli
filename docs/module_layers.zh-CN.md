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

Go host 内部还有一条必须遵守的拆分：

| 使用方 | 放哪里 | 不要放 |
|--------|--------|--------|
| **`flashcli` CLI 与 `flashserver` 都用** —— 缓存发现、权重 key/就绪判断、runtime ID/路径、磁盘统计、ref 路径解析、清理 | `go/internal/host` | `go/internal/cli`、`go/internal/server` |
| **仅一个前端用** —— 参数解析、渲染、HTTP handler、进程启动 | `go/internal/cli` 或 `go/internal/server` | `go/internal/host` |

**模型专属逻辑绝不放在 host：** 前向、预处理/后处理、模态形状/dtype、option→端口映射与默认值都属于 bundle——Python `entry`，或（native kind）model-runtime `.so` + manifest `native` 声明/运行时 port 描述符。`go/internal/` 只承载**与模型无关的协议管道**（例如按 bundle 声明的端口构造 ABI 载荷）。在 host 里写死某模型的常量、形状或预处理即为缺陷。

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

## Protocol 模块（`flashcli_bundle/`）

共享类型、manifest/options、paths、FlashHub client、preset/weights/cache 逻辑的规范归属（不含 HTTP serve 栈、不含 HF hub）。

| 模块 | 职责 |
|------|------|
| `protocol.py` | `RunEngine` / `ServeEngine` / 请求类型 |
| `manifest.py`、`manifest_ext.py` | manifest 加载 + 布局校验 |
| `manifest_resolve.py`、`help_text.py` | 仅用于 help 的 manifest 解析 |
| `options.py`、`catalog.py`、`preset.py`、`preset_ref.py` | ref 解析、preset 视图 |
| `paths.py`、`marker.py`、`context.py`、`errors.py` | 路径、marker、激活上下文 |
| `flashhub.py`、`flashhub_errors.py` | FlashHub index/manifest 下载 |
| `openai_compat.py` | OpenAI 兼容 helper（不含 starlette） |
| `native*.py`、`layout.py`、`checkpoint.py`、`weights_spec.py` | bundle 布局 + checkpoint 规则 |
| `runtime/detect.py`、`runtime/requirements_spec.py`、`runtime/mirror.py` | GPU/CUDA、pip spec、镜像 |
| `cache.py`、`post_pull.py`、`resolve.py`、`weights.py`（解析）、`activate_core.py` | 两层共用；下载/HF 逻辑留在 host |

**非 protocol（host-only）：** 权重下载、FlashHub sync 组装、venv 供应、re-exec —— 全在 `go/internal/`。

## Host（Go，`go/internal/`）

命令树、FlashHub sync、权重下载、preflight、venv、backend 分派。**不** import Python infer 代码。

| 包 | 职责 |
|----|------|
| `host` | **CLI 与 flashserver 共用的缓存/运行时服务层**：marker、bundle 可用性/serve 能力、权重 key/就绪、每 bundle 运行时路径/大小、磁盘统计、ref 路径解析、清理 |
| `cli` | 面向用户的命令（`run`/`serve`/`pull`/`bundle`/`models`/`cache`/`doctor`/`du`/`upgrade`/`version`） |
| `ref`、`flashhub` | ref 解析、FlashHub index + 树同步 |
| `weights` | HF/ModelScope 下载、缓存、`post_pull`、`extra_pull` |
| `preflight`、`native`、`hostabi`、`cuda` | env-key 匹配、native cell 校验、宿主 ABI、CUDA userland |
| `venv`、`pythonprovision` | bundle venv 创建 + 基础 Python 供应 |
| `inferexec`、`nativeexec`、`nativeabi` | 执行后端（`entry.kind`） |
| `manifest` | manifest 解析 + 校验 |
| `server` | `flashserver` HTTP API（`docs/openapi.yaml`）+ `/v1/ws` 状态流、模型生命周期/任务、内嵌控制台（`go/internal/server/web`） |
| `setup` | `flashserver-setup`：Linux systemd 单元、Windows `flashserver_ubuntu` WSL2 发行版 + 登录任务 + 防火墙规则、卸载/清理 |
| `serveopts`、`gpu`、`system`、`progress`、`mirror` | 已保存的每模型 serve 参数、nvidia-smi 遥测、宿主能力探测、任务进度、镜像环境 |
| `paths`、`runtime`、`selfupdate`、`postpull`、`version`、`errs` | 支撑 |

`go/cmd/` 下的二进制只做参数解析与组装：`flashcli`（CLI）、`flashserver`
（守护进程 + 控制台）、`flashserver-setup`（Windows 安装包使用的安装后端）。
桌面客户端（`desktop/`，Rust/egui）在 Go 模块之外，只通过 HTTP API 通信
（见 [architecture.zh-CN.md](architecture.zh-CN.md#本地服务栈desktopflashserverflashserver-setup)）。

## Infer 模块（`flashcli_bundle/infer/`）

bundle venv 入口：`python -m flashcli_bundle.infer run|serve`。

| 模块 | 职责 |
|------|------|
| `__main__.py`、`app.py`、`cli.py` | bundle argv + 分派 |
| `engines/*`、`serve/*` | engine 加载 + FastAPI/uvicorn |
| `deps.py`、`runtime/bundle_venv.py` | bundle venv pip（只读路径） |
| `bundle/resolve.py` | `activate_for_preset`（infer 激活路径） |

**仅 re-export**（共享 protocol）：`preset.py`、`preset_ref.py`、`cache.py`、`runtime/detect.py`、`runtime/mirror.py` 等。

**infer-only wrapper**：`bundle/weights.py`、`bundle/activate.py`。

## Enforcement

- **Protocol** `flashcli-bundle/pyproject.toml` 保持 `dependencies = []`；infer extra 含 serve 栈、不含 `huggingface_hub`。
- **执行 ABI / host 对等**由 `tests/conformance/` 强制（命令面对等、Py↔Go execution ABI 一致、re-exec/原生 backend）。
- **Go host** 由 `go test ./...` 覆盖。
- **共享 host 逻辑**由 `go/internal/host` 测试 + `go/internal/cli` 的 `du`/`models list`/`bundle clean` 测试强制，这些测试走 flashserver 同一套 host 函数。禁止在 `cli`/`server` 再写 marker 遍历、权重就绪判断、大小遍历或清理路径解析；新逻辑放进 `host` 并同时覆盖两个前端。
- Python host（`src/flashcli/`）已移除；不要重新把 host 专有代码放回 `flashcli_bundle/`。

详见 [architecture.zh-CN.md](architecture.zh-CN.md)。
