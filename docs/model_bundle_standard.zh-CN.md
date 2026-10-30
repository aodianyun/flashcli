# Model Bundle — preset ref 与运行时流程

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

面向 **集成方** 对接 preset 与 FlashHub。manifest、entry、`.so` 完整规范 → **[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)**。

## 从 FlashHub 发现 bundle

已发布的 Model Bundle 在 **[FlashHub](https://flashhub.top)**。在站点选择 repo/版本后，将 ref 传给 flashcli。flashcli 仓库内**无 bundled catalog 文件**。

`flashcli models list` 显示**本机已缓存**的 ref 及其 bundle/weights 磁盘占用（在 `run`、`serve`、`pull` 或 `bundle sync` 之后）。

## Preset ref（FlashHub）

```text
namespace/bundle:version
```

示例：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.5
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0
```

| 部分 | 含义 |
|------|------|
| `namespace/bundle:version` | FlashHub repo 名 + 固定版本 |
| 完整 URL | `https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.5` 也可 |

**API 基址**（环境变量）：`FLASHCLI_FLASHHUB_API`（默认 `https://flashhub-api.aodianyun.com/api/v1/repos`）。  
在 **[flashhub.top](https://flashhub.top)** 浏览已发布 bundle（对外站点）；API 尚未迁移至该域名。  
拼出 repo URL：`{FLASHCLI_FLASHHUB_API}/{namespace}/{bundle}:{version}`。

**本地开发**（positional，路径下须有 `flashcli-bundle.json`）：

```bash
flashcli run bundles/pi05_libero
flashcli pull bundles/pi05_libero
```

## 环境选择

host 先匹配精确 `environments.<env>` key；没有精确匹配时，再按 fallback 的 `match` 维度（`os`、`arch`、`python_abi`，可选 `vendor`、`sm`、`cuda`）选择，匹配维度越多越优先。多个 environment 可共享同一 runtime 目录；没有 runtime 的 environment 是纯 Python/CPU fallback。


## sync 后目录

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<runtime-dir>/
```

> 仅原生 bundle（`defaults.entry.kind = native-abi|native-exec`）省略 `run.py`/`serve.py` 与 `flash_rt/`；C 库放在 `runtime/<runtime-dir>/substrate/`。

权重不在 bundle 内。v4 使用按 `source + repo + revision` 派生的共享 store（通常在 `~/.flashcli/models/store/...`）；extra weights 默认 `<store>/extra/<key>/`。

## 终端用户运行时流程

1. 解析 REF → 若为本地目录则用 `local_root`；否则 `bundle.repo`（或已 sync 的 marker）
2. FlashHub manifest → 本机 **preflight** env key
3. 下载 entry + 匹配的 `runtime/<runtime-dir>/`
4. `kind=python`：创建 bundle venv（`python_abi`、manifest 中的 torch）。native kind 跳过 venv。
5. `kind=python`：在 bundle venv 内 **re-exec** infer — [architecture.zh-CN.md](architecture.zh-CN.md)。`native-exec`/`native-abi`：host 直接 spawn / `dlopen` bundle backend。
6. **主机**（推理前）：确保 `weights` + `extra_weights` + `post_pull`。主机在**传输前**把远端预期文件集写入 `<weights_dir>/.flashcli_download.json`，中断后按预期集续传；完整清单可离线接受；`flashcli pull` 会重新列远端并重写清单。7. **bundle**：仅解析本地 checkpoint（`HF_HUB_OFFLINE=1`）；运行 `entry`（或原生 backend）

`flashcli pull <ref>` 执行步骤 1–6，不进入推理。首次 `flashcli run` / `serve` 在 cache 为空时也会自动执行 1–6。

`flashcli bundle sync <ref>` 仅预拉 FlashHub 目录树（不含权重）。

**环境与权重来源**（`flashcli models show <ref>`）：host 从 `flashcli-bundle.json` 中精确 environment 或 fallback 选择；weights 的 `source`/`repo`/`revision` 来自同一 manifest。多个 environment 可共享一个 runtime 目录。

## 执行 backend（`entry.kind`）

bundle 的 `entry` 决定 flashcli 如何调用推理。无论哪种，用户命令都不变：

| `entry.kind` | backend |
|--------------|---------|
| `python`（默认） | bundle venv re-exec → `python -m flashcli_bundle.infer` |
| `native-exec` | host 启动 bundle 可执行文件（NDJSON stdio / HTTP） |
| `native-abi` | host `dlopen` 一个 `frt_model_runtime_v1` `.so` 并在进程内驱动 |

没有 `entry.kind` 的 bundle 行为完全不变。完整契约见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。

## 快速校验

```bash
flashcli models list          # 缓存 ref + 每个 ref 的 bundle/weights 占用
flashcli models show <ref>
flashcli du                   # bundles/models/runtimes/cache 总占用
flashcli bundle validate /path/to/bundle
flashcli run <ref> --help
```
