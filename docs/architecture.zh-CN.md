# 架构说明

<p align="right"><a href="architecture.md">English</a> · <strong>简体中文</strong></p>

flashcli 是 FlashRT 的**分发与运行宿主**：解析 preset、从 FlashHub 拉取 Model Bundle、按 GPU 环境 preflight、创建 bundle venv、缓存权重，并调用 bundle 内 **`entry`** 的 `RunEngine` / `ServeEngine`。

**不负责**具体模型 forward、CUDA kernel；这些在 bundle 的 `run.py`（及 `flash_rt/`、`.so`）中实现。**仅原生** bundle 则改用原生 model-runtime ABI、无 Python entry（`entry.kind = native-abi|native-exec`；见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)）。

> **Go host。** 主机 CLI 是 `go/`（module `github.com/aodianyun/flashcli/go`）下的静态 Go 二进制；Python host 已移除。`flashcli-bundle/` 保留：它是装进 bundle venv 的 **protocol** + **infer** 包（`flashcli-bundle[infer]`）。执行 backend（`entry.kind`）规范见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。

## 核心原则

1. **推理在 bundle 内** — bundle 拥有**全部模型专属逻辑**：前向、预处理/后处理、模态形状与 dtype、输入/输出语义、option→端口映射与默认值。flashcli 只是**通用、与模型无关的驱动器**：解析 ref、准备环境、调用 bundle 提供的接口——`kind=python` 用 `entry`，`native-exec`/`native-abi` 用声明的 model-runtime ABI + manifest `native` 块。**host（`go/`）中不得出现任何模型专属常量、形状或预处理。**
2. **Preset ref** — 用户使用 `namespace/bundle:version[@variant]`；`FLASHCLI_FLASHHUB_API` 配置 API 基址。
3. **manifest-first + 分包下载** — 先拉 manifest → preflight 匹配 `runtime` env key → 只下载本 env 的 `runtime/<env-key>/`。
4. **固定 Python ABI** — 每个 bundle 一个 venv（`python_abi`）；CLI 准备完成后 **re-exec** 进 bundle venv。
5. **单一 Go 主机** — 主机为 `go/` 静态二进制；bundle venv 仅 pip **`flashcli-bundle[infer]`**（protocol + infer）。
6. **一条命令** — `flashcli run <preset>` 串联：sync → 依赖 → 权重（主机缺失则下载）→ `post_pull` → bundle venv 内离线推理。

### 模块放哪（必读）

**主机（Go）→ `go/internal/*`；只有 infer 用到 → `flashcli_bundle/infer/`；两层都用 → `flashcli_bundle/` protocol。** Re-export 不能作为把逻辑塞进 protocol 的理由。详见 [module_layers.zh-CN.md](module_layers.zh-CN.md)。

## 主机 CLI 与 bundle infer（必读）

`flashcli pull` / `bundle sync` / 权重下载在 **Go 主机**中执行。  
`flashcli run` / `serve` 先准备 bundle，随后：`entry.kind: python` 时 **re-exec** 到 **bundle venv**（`python -m flashcli_bundle.infer`）；`native-exec` / `native-abi` 时驱动原生 backend。

| 内容 | 位置 | 安装方式 |
|------|------|----------|
| `flashcli` CLI | PATH 上的 Go 二进制（`go/`） | `install.sh` |
| **`flashcli-bundle`**（协议） | 主机（build/开发） | `flashcli-bundle/` 源码 |
| **`flashcli-bundle[infer]`** | 仅 bundle venv | `venv.Ensure` → pip（`FLASHCLI_BUNDLE_PIP_SPEC` / repo / 本地 checkout） |
| 推理栈（torch、transformers…） | `~/.flashcli/runtimes/<id>/venv/` | `flashcli-bundle.json` → `python_dependencies` |

**依赖隔离：** 主机除 `flashcli-bundle[infer]` 与 manifest `python_dependencies` 外不向 bundle venv 安装任何东西。权重下载仅在**主机**执行；bundle infer 子进程只解析缓存或 bundle 本地路径（`HF_HUB_OFFLINE=1`）。

**协议缓存 schema：** venv 的 fingerprint 只跟踪 manifest `python_dependencies`，**不跟踪** `flashcli-bundle` 的 git ref。当磁盘缓存布局变化（`flashcli_bundle.version.CACHE_SCHEMA_VERSION`）时，`venv.EnsureProtocolCacheSchema` 会在 re-exec 前把已有 venv 里的 `flashcli-bundle` **就地升级**（`pip install --upgrade --force-reinstall --no-deps`，来源不变），使旧 venv 无需整体重建即可与主机缓存路径保持一致（不重装 torch/依赖）。

**Re-exec 命令**（在 bundle venv 内）：

```text
bundle_venv/bin/python -m flashcli_bundle.infer run|serve …
```

bundle venv **不** prepend 主机 `PYTHONPATH`。实现：Go `internal/{inferexec,nativeexec,nativeabi}` + `flashcli-bundle` 的 `flashcli_bundle.infer`。

### 禁止事项（避免再次跑偏）

- **不要**在 bundle venv 里 `pip install flashcli` — infer 在 `flashcli-bundle[infer]` 中。
- **不要**把主机 ``site-packages`` 或主机 ``flashcli`` 放进 bundle 进程的 ``PYTHONPATH`` — 否则主机的 ``huggingface_hub`` 1.x 会泄漏到 bundle（实现 bug，非设计）。

`activate_bundle()` 还会把 **bundle 根目录** prepend 到 `PYTHONPATH`，以便 `import entry` / `flash_rt`。

## 与 FlashRT 的边界

| 职责 | flashcli | Model Bundle |
|------|----------|----------------|
| Preset ref / FlashHub | ✓ | |
| `flashcli-bundle.json` | | ✓ |
| FlashHub 拉取 / 本地 `path` | ✓ | |
| bundle venv、PYTHONPATH、pip | ✓ | `python_dependencies` |
| OpenAI HTTP（`serve`） | ✓ | |
| `RunEngine` / `ServeEngine` | | ✓ |
| `flash_rt`、`*.so` | | ✓ |

flashcli **不** pip 依赖 `flash-rt`。`import flash_rt` 仅在 `activate_bundle()` 之后可用。

## 数据流（`flashcli run flashcli-bundle/pi05_libero:1.0.4`）

```mermaid
sequenceDiagram
  participant U as 用户
  participant CLI as flashcli（Go host）
  participant FH as flashhub
  participant Pre as preflight
  participant W as weights
  participant Venv as venv
  participant Infer as flashcli_bundle.infer

  U->>CLI: flashcli run flashcli-bundle/pi05_libero:1.0.4
  CLI->>FH: 拉取 repo index（若未 sync）
  FH-->>CLI: files[] + download_url
  CLI->>FH: 同步 entry 树 + runtime/<env-key>/
  CLI->>Pre: env key + native cell + host ABI + CUDA userland
  CLI->>W: ensure 权重（+ post_pull/extra_pull）
  CLI->>Venv: 创建 bundle venv + torch 依赖
  CLI->>Infer: re-exec: bundle python -m flashcli_bundle.infer
  Note over Infer: bundle venv: flashcli-bundle[infer] only
  Infer->>Infer: activate + 本地 checkpoint + RunEngine/ServeEngine/script
```

**Entry modes**: `engine`（默认）加载 `RunEngine`/`ServeEngine` 并解析 manifest CLI 选项；`script` 将 argv 透传给 bundle 入口脚本，主机侧仅根据 `--checkpoint` 决定权重拉取。

**Backends**：`entry.kind` 选择 `python`（re-exec，如上）、`native-exec`（主机 spawn）或 `native-abi`（主机 `dlopen`）。见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。

**Bundle 解析顺序**：本地 positional path（含 `flashcli-bundle.json` 的目录）> 已 sync 的 bundle 缓存（`bundles/<cache-key>/` 下 preset marker）；FlashHub ref 由 `bundle sync` 同步。

## 权重缓存：下载完整性 vs 就绪（离线保证）

两项独立检查，刻意分开：

1. **主机 —— 下载完整性。** 列出远端文件集（并应用 bundle 的 `allow_patterns`）后，
   主机在**传输前**把预期集写入 `<weights_dir>/.flashcli_download.json`
   （`path`、`size`）。只有清单内每个文件都存在且 size 匹配时才算完整。
   下载失败时保留预期集，下一次只补缺失/大小不符的文件；下载进行中或中断时，
   `<weights_dir>/.flashcli_download.incomplete` 存在。该检查与模型无关，绝不含
   bundle 专属文件名。主权重与每个 `extra_weights` 目标各自有清单。
2. **Bundle —— 就绪。** `flashcli-bundle.json` 声明 entry 需要什么
   （`allow_patterns`、`require_any_patterns`、`require_norm_stats`）；主机仅用这些
   规则判断“该 bundle 是否可用”。

**网络策略 —— `run`/`serve` 本地优先：**

- 有**完整的下载清单** → 本地校验 + bundle 就绪（不联网）；
- **无清单且无 incomplete 标记的旧缓存** → 按 bundle 声明在**本地**判断就绪（不联网）；
- 清单文件存在但无法解析时**绝不**当作旧缓存，主机会重新列远端；
- 清单缺失（且未接受旧缓存）或不完整时，`run`/`serve` 自动准备（需要联网）并按预期集续传；
  显式 `flashcli pull` 总是重新列远端并重写预期集，即使本地清单已完整。

因此**一旦准备成功**（bundle 树 + 权重 + venv/依赖），此后每次 `run`/`serve` 都**离线可用**。
只有产物缺失、显式 `flashcli pull` 或协议 `CACHE_SCHEMA_VERSION` 变化需要升级 venv 内
`flashcli-bundle` 时才需要联网。

清单存在但**不完整时绝不接受**，即使宽松的 bundle 就绪判定会通过；中断的下载可凭已记录的
预期集续传。

## Bundle venv 安装器（uv）

bundle venv 默认用 **uv** 创建与安装（仍保持每模型隔离）。uv **不随 flashcli 发布**：`uv.Ensure` 依次解析 `FLASHCLI_UV_BIN` → `PATH` 上的 `uv` → 已供给的副本；否则从配置的 PyPI 索引（国内镜像）按需下载并校验 sha256，安装到 `~/.flashcli/tools/uv/<version>/`。

- 供给优先使用配置的 **PyPI 索引**（最新稳定 wheel，校验 sha256）；索引不可达时先查 **GitHub latest release**，再退回内置默认版本，并下载 **GitHub Release** 的 tarball（校验 sha256）。
- `uv venv --python <base> --seed` 建 venv；`uv pip install --python …` 安装 `flashcli-bundle[infer]`、torch 与 manifest 依赖。协议升级与 CUDA userland 安装也走同一安装器。
- `UV_CACHE_DIR` 默认 `~/.flashcli/cache/uv`（与 `runtimes/` 同文件系统，uv 用**硬链接**共享 wheel，torch/CUDA 重层只存一份）；`UV_LINK_MODE=hardlink`。
- `FLASHCLI_VENV_BACKEND=pip` 是显式逃生口（已弃用）；默认 `uv` 在不可用时明确报错。native bundle 不需要 uv。
- venv 建好后即可离线使用（uv 只在安装时需要）；`flashcli cache clean [--uv|--tools|--all]` 可清理 uv 缓存/已供给二进制，不影响已建 venv；`flashcli cache prune` 清理 uv 中不可达的缓存对象（较保守；`cache clean` 才会全部清空）。

## 本机目录

```text
~/.flashcli/
├── install.env              # flashcli-bundle[infer] 来源：本地 checkout（源码构建）或 repo/ref（发布安装）
├── mirror.env               # install.sh --mirror 写入（pip/HF/GitHub 镜像）
├── src/                     # --from-source 源码 checkout（构建输入；默认 ~/.flashcli/src）
├── python/                  # 可选：standalone Python，供 bundle venv 使用
├── python-runtime.env       # provision standalone Python 后写入 FLASHCLI_PY<abi>_BIN=…
├── runtimes/<id>/           # bundle venv + .runtime.json marker
├── bundles/<name>/<version>/.flashcli_bundle.json   # 同步树（所有 @variant 共享）
├── cache/repo-index/        # FlashHub listing 缓存
├── cache/uv/                # uv 包缓存（默认 UV_CACHE_DIR）
├── tools/uv/<version>/      # 已供给的 uv 二进制
└── models/<name>/<version>/<weights_dir>/           # 各 variant 权重（默认 checkpoint/）+
                                                       #   .flashcli_download.json / .flashcli_download.incomplete
```

## Bundle 布局（sync 后）

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py
├── flash_rt/
└── runtime/<env-key>/       # 本机 native *.so（就地加载，不拷贝到 lib/）
```

> 仅原生 bundle 省略 `run.py` / `flash_rt/`，C 库放在 `runtime/<env-key>/substrate/`。

详见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 模块划分

权威的 host / infer / protocol 包划分与归属规则见 [module_layers.zh-CN.md](module_layers.zh-CN.md)。

## 示例 ref

| Ref | 能力 | 说明 |
|-----|------|------|
| `flashcli-bundle/pi05_libero:1.0.4` | `run` | Pi0.5 LIBERO |
| `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` | `run`, `serve` | Qwen3-8B |
| `flashcli-bundle/qwen_nvfp4:1.0.1@qwen36` | `run`, `serve` | Qwen3.6-27B + MTP |
| `bundles/groot_n16` *（本地 dev）* | `run` | GROOT N1.6 |
| `bundles/groot_n17` *（本地 dev）* | `run` | GROOT N1.7 |

见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 相关文档

- [module_layers.md](module_layers.md) — 三层模块归属与 import 规则
- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — preset ref + 运行时流程
- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) — manifest 与 entry 规范
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) — 执行 backend（`entry.kind`）与原生契约
