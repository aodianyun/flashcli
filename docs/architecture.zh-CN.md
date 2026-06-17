# 架构说明

<p align="right"><a href="architecture.md">English</a> · <strong>简体中文</strong></p>

flashcli 是 FlashRT 的**分发与运行宿主**：解析 preset、从 FlashHub 拉取 Model Bundle、按 GPU 环境 preflight、创建 bundle venv、缓存权重，并调用 bundle 内 **`entry`** 的 `RunEngine` / `ServeEngine`。

**不负责**具体模型 forward、CUDA kernel；这些在 bundle 的 `run.py`（及 `flash_rt/`、`.so`）中实现。

## 核心原则

1. **推理在 bundle 内** — `flashcli-bundle.json` 的 `entry` 指向模块；flashcli 只做 `importlib` 加载。
2. **Preset ref** — 用户使用 `namespace/bundle:version[@variant]`；`FLASHCLI_FLASHHUB_API` 配置 API 基址。
3. **manifest-first + 分包下载** — 先拉 manifest → preflight 匹配 `runtime` env key → 只下载本 env 的 `runtime/<env-key>/`。
4. **固定 Python ABI** — 每个 bundle 一个 venv（`python_abi`）；CLI 准备完成后 **re-exec** 进 bundle venv。
5. **主机只装一份 flashcli** — **绝不**向 bundle venv pip 安装 flashcli CLI；bundle venv 只装 **`flashcli-bundle`**（协议层）。re-exec 仅通过 ``host_flashcli_import_root()`` 加载主机 ``runtime.infer``（见下节）。
6. **一条命令** — `flashcli run <preset>` 串联：sync → 依赖 → 权重 → `post_pull` → 推理。

## 主机 CLI 与 bundle infer（必读）

`flashcli pull` / `bundle sync` / 权重下载在**主机 CLI venv**（如 `install.sh` 的 Python 3.10）中执行。  
`flashcli run` / `serve` 先准备 bundle，再 **re-exec** 到 **bundle venv**（如 manifest 的 Python 3.12）。

| 内容 | 位置 | 安装方式 |
|------|------|----------|
| `flashcli` CLI + infer 模块 | 仅主机（`~/.flashcli/venv` 或 editable `src/`） | `install.sh` / `auto_install.sh`，**只装一次** |
| **`huggingface_hub`**（Hub CLI、拉权重） | **仅主机** | `pyproject.toml` — **不**装进 bundle venv |
| **`flashcli-bundle`**（协议、manifest options） | 主机 + bundle venv | Git：`flashcli-bundle @ git+…#subdirectory=flashcli-bundle`（见 `install.sh`、`~/.flashcli/install.env`） |
| 推理栈（torch、transformers…） | `~/.flashcli/runtimes/<id>/venv/` | `flashcli-bundle.json` → `python_dependencies` |
| infer 辅助依赖（typer、pyyaml、fastapi…） | 同上 bundle venv，**缺啥装啥** | `ensure_bundle_infer_deps()` — **不含** `huggingface_hub`；不含 flashcli 包本身 |

**依赖隔离：** 主机与 bundle venv 相互独立。flashcli 不为 bundle 栈 pin `transformers` 或限制 `huggingface_hub` 版本 — bundle 的 `python_dependencies`（如 `transformers<4.56`）在 bundle venv 内自行解析传递依赖。权重下载（`flashcli pull`，或 `run`/`serve` 前自动 pull）仅在**主机**执行；bundle infer 子进程只解析缓存或 bundle 本地路径。

**Re-exec 命令**（在 bundle venv 内）：

```text
bundle_venv/bin/python /path/to/host/flashcli/runtime/infer_launch.py run|serve …
```

``infer_launch.py`` 通过 ``host_flashcli_import_root()`` 只暴露主机 ``flashcli`` 包（``$FLASHCLI_HOME/host-import/`` symlink 或 editable ``src/``），**绝不** prepend 主机 ``site-packages``。启动时 ``runtime/isolation.validate_host_import_root`` 校验。实现：`runtime/reexec.py`、`runtime/infer_launch.py`、`runtime/flashcli_shared.py`。

### 禁止事项（避免再次跑偏）

- **不要**在 bundle venv 里 `pip install flashcli` — dev 版本通常不在 PyPI。
- **不要**按 `python_abi` 再复制一份 flashcli — 主机 `sys.path` 引导共用即可；按 ABI 变化的只有 bundle **依赖**。
- **不要**把主机 ``site-packages`` 放进 bundle 进程的 ``PYTHONPATH`` / ``sys.path`` — 只需能 ``import flashcli``；否则主机的 ``huggingface_hub`` 1.x 会被 bundle ``transformers`` 的 metadata 检查看到（实现 bug，非设计）。

`activate_bundle()` 还会把 **bundle 根目录** prepend 到 `PYTHONPATH`，以便 `import entry` / `flash_rt`（与 re-exec 时加载主机 flashcli 是两层不同用途）。

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
  participant Infer as runtime.infer
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
  CLI->>Infer: re-exec: bundle python -m flashcli.runtime.infer
  Note over Infer: PYTHONPATH = 主机 flashcli 安装路径
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
| `runtime/reexec.py` | 主机准备 → re-exec 进 bundle venv |
| `runtime/infer_launch.py` | 启动器：prepend 主机 flashcli 到 `sys.path` |
| `runtime/infer.py` | 在 bundle venv 内执行 `run` / `serve` |
| `runtime/flashcli_shared.py` | 主机 `PYTHONPATH`，不二次安装 flashcli |
| `deps.py` | 主机 / bundle pip 列表；`ensure_bundle_infer_deps()` — 仅 typer/yaml/… 进 bundle venv（无 hub） |
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

- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — preset ref + 运行时流程
- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) — manifest 与 entry 规范
