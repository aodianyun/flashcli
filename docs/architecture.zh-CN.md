# 架构说明

<p align="right"><a href="architecture.md">English</a> · <strong>简体中文</strong></p>

flashcli 是 FlashRT 的**分发与运行宿主**：解析 preset、从 FlashHub 拉取 Model Bundle、按 GPU 环境 preflight、创建 bundle venv、缓存权重，并调用 bundle 内 **`entry`** 的 `RunEngine` / `ServeEngine`。

**不负责**具体模型 forward、CUDA kernel；这些在 bundle 的 `run.py`（及 `flash_rt/`、`.so`）中实现。

## 核心原则

1. **推理在 bundle 内** — `flashcli-bundle.json` 的 `entry` 指向模块；flashcli 只做 `importlib` 加载。
2. **Preset ref** — 用户使用 `namespace/bundle:version[@variant]`；`FLASHCLI_FLASHHUB_API` 配置 API 基址。
3. **manifest-first + 分包下载** — 先拉 manifest → preflight 匹配 `runtime` env key → 只下载本 env 的 `runtime/<env-key>/`。
4. **固定 Python ABI** — 每个 bundle 一个 venv（`python_abi`）；CLI 准备完成后 **re-exec** 进 bundle venv。
5. **主机只装一份 flashcli** — 主机 venv 仅 pip **`flashcli-bundle`**（协议）；bundle venv pip **`flashcli-bundle[infer]`**。主机代码**禁止** `import flashcli_bundle.infer`。
6. **一条命令** — `flashcli run <preset>` 串联：sync → 依赖 → 权重 → `post_pull` → 推理。

### 模块放哪（必读）

**只有 host 用到 → `src/flashcli/`；只有 infer 用到 → `flashcli_bundle/infer/`；两层都用 → `flashcli_bundle/` protocol。** Re-export 不能作为把 host/infer 专有逻辑塞进 protocol 的理由。详见 [module_layers.zh-CN.md](module_layers.zh-CN.md)。

## 主机 CLI 与 bundle infer（必读）

`flashcli pull` / `bundle sync` / 权重下载在**主机 CLI venv**（如 `install.sh` 的 Python 3.10）中执行。  
`flashcli run` / `serve` 先准备 bundle，再 **re-exec** 到 **bundle venv**（如 manifest 的 Python 3.12）。

| 内容 | 位置 | 安装方式 |
|------|------|----------|
| `flashcli` CLI | 仅主机（`~/.flashcli/venv` 或 editable `src/`） | `install.sh` / `auto_install.sh` |
| **`huggingface_hub`**（Hub CLI、拉权重） | **仅主机** | `pyproject.toml` — **不**装进 bundle venv |
| **`flashcli-bundle`**（协议） | 仅主机 | Git：`flashcli-bundle @ git+…#subdirectory=flashcli-bundle` |
| **`flashcli-bundle[infer]`** | 仅 bundle venv | 同上，带 `[infer]` extra |
| 推理栈（torch、transformers…） | `~/.flashcli/runtimes/<id>/venv/` | `flashcli-bundle.json` → `python_dependencies` |

**依赖隔离：** 主机与 bundle venv 相互独立。flashcli 不为 bundle 栈 pin `transformers` 或限制 `huggingface_hub` 版本 — bundle 的 `python_dependencies`（如 `transformers<4.56`）在 bundle venv 内自行解析传递依赖。权重下载（`flashcli pull`，或 `run`/`serve` 前自动 pull）仅在**主机**执行；bundle infer 子进程只解析缓存或 bundle 本地路径。

### Pip 依赖分层

| 层级 | Venv | 安装方式 | 禁止 |
|------|------|----------|------|
| `flashcli` | 主机 | `pyproject.toml` | import `flashcli_bundle.infer` |
| `flashcli-bundle` | 主机 | `install.sh`（无 extras） | — |
| `flashcli-bundle[infer]` | Bundle | `ensure_flashcli_bundle_in_venv(..., extras=("infer",))` | import 主机 `flashcli` |
| Manifest `python_dependencies` | Bundle | `activate_bundle` / `bundle install` | pin 主机 `huggingface_hub` |

结构测试：`tests/test_architecture_layers.py`。

**Re-exec 命令**（在 bundle venv 内）：

```text
bundle_venv/bin/python -m flashcli_bundle.infer run|serve …
```

bundle venv **不** prepend 主机 `PYTHONPATH`，**不** import 主机 `flashcli`。实现：`runtime/reexec.py`、`flashcli-bundle` 的 `flashcli_bundle.infer` 包。

### 禁止事项（避免再次跑偏）

- **不要**在 bundle venv 里 `pip install flashcli` — infer 在 `flashcli-bundle[infer]` 中。
- **不要**把主机 ``site-packages`` 或主机 ``flashcli`` 放进 bundle 进程的 ``PYTHONPATH`` — 否则主机的 ``huggingface_hub`` 1.x 会泄漏到 bundle（实现 bug，非设计）。

`activate_bundle()` 还会把 **bundle 根目录** prepend 到 `PYTHONPATH`，以便 `import entry` / `flash_rt`。

## 与 FlashRT 的边界

| 职责 | flashcli | Model Bundle |
|------|----------|----------------|
| Preset ref / FlashHub | ✓ | |
| `flashcli-bundle.json` | | ✓ |
| FlashHub 拉取 / 本地 `local_root` | ✓ | |
| bundle venv、PYTHONPATH、pip | ✓ | `python_dependencies` |
| OpenAI HTTP（`serve`） | ✓ | |
| `RunEngine` / `ServeEngine` | | ✓ |
| `flash_rt`、`*.so` | | ✓ |

flashcli **不** pip 依赖 `flash-rt`。`import flash_rt` 仅在 `activate_bundle()` 之后可用。

## 数据流（`flashcli run flashcli-bundle/pi05_libero:1.0.3`）

```mermaid
sequenceDiagram
  participant U as 用户
  participant CLI as cli（主机 venv）
  participant Infer as flashcli_bundle.infer
  participant FH as bundle.flashhub
  participant Art as bundle.artifacts
  participant Venv as runtime.bundle_venv
  participant Act as bundle.activate
  participant Cache as models.cache
  participant Ldr as engines.loader

  U->>CLI: flashcli run flashcli-bundle/pi05_libero:1.0.3
  CLI->>Art: ensure_runtime（若无缓存）
  Art->>FH: fetch_repo_index(repo URL)
  FH-->>Art: files[] + download_url
  Art->>Art: manifest + preflight + 下载 runtime/
  Art->>Venv: 创建 bundle venv + torch 依赖
  CLI->>Infer: re-exec: bundle python -m flashcli_bundle.infer
  Note over Infer: bundle venv: flashcli-bundle[infer] only
  Infer->>Act: activate_bundle
  Infer->>Cache: ensure_model_cached + post_pull
  Infer->>Ldr: entry.run.RunEngine
  Ldr->>U: actions
```

**Bundle 解析顺序**：本地 positional path（含 `flashcli-bundle.json` 的目录）> 已 sync 的 runtime 缓存（`FLASHCLI_BUNDLE_ROOT` / preset marker）；FlashHub ref 的 `repo` 由 `bundle sync` 填充缓存。

## 本机目录

```text
~/.flashcli/
├── venv/                    # 主机 CLI（flashcli 只装此处）
├── python/                  # 可选：standalone Python，供 bundle venv 使用
├── runtimes/<id>/           # sync 后的 bundle 根 + bundle venv
├── bundles/<bundle>/<version>@<variant>/.flashcli_bundle.json
├── cache/repo-index/        # FlashHub listing 缓存
└── models/<bundle>/<version>@<variant>/checkpoint/
```

## Bundle 布局（sync 后）

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py
├── flash_rt/
└── runtime/<env-key>/       # 本机 native *.so（就地加载，不拷贝到 lib/）
```

详见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 模块划分

| 包 | 职责 |
|----|------|
| `models/preset_ref.py` | 解析 ref → repo URL + variant + cache key |
| `bundle/catalog.py` | 从 preset ref 解析 `bundle.repo` |
| `bundle/flashhub.py` | FlashHub API  listing / 文件下载 |
| `bundle/artifacts.py` | manifest-first 组装 runtime |
| `bundle/preflight.py` | env key 与 `runtime` 匹配 |
| `bundle/resolve.py` | 本地 path / 已 sync 缓存 |
| `bundle/activate.py` | PYTHONPATH、依赖、预加载 `.so` |
| `runtime/bundle_venv.py` | 按 `python_abi` 创建 venv |
| `runtime/reexec.py` | 主机准备 → re-exec：`python -m flashcli_bundle.infer` |
| `flashcli_bundle.infer` | 在 bundle venv 内执行 `run` / `serve`（`flashcli-bundle[infer]`） |
| `deps.py` | 主机 pip + `flashcli-bundle`；bundle venv 经 `ensure_flashcli_bundle_in_venv(..., extras=("infer",))` |
| `models/cache.py` | 主机拉权重 + 缓存；bundle infer 仅解析路径 |
| `engines/loader.py` | 加载 `entry` |

## 示例 ref

| Ref | 能力 | 说明 |
|-----|------|------|
| `flashcli-bundle/pi05_libero:1.0.3` | `run` | Pi0.5 LIBERO |
| `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` | `run`, `serve` | Qwen3-8B |
| `flashcli-bundle/qwen_nvfp4:1.0.1@qwen36` | `run`, `serve` | Qwen3.6-27B + MTP |

见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 相关文档

- [module_layers.md](module_layers.md) — 三层模块归属与 import 规则
- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — preset ref + 运行时流程
- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) — manifest 与 entry 规范
