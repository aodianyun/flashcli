# flashcli Model Bundle（format_version 3）

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

第三方通过 **Model Bundle** 交付推理 runtime。flashcli **仅**加载 bundle 并调用 `entry`，不在 flashcli 源码中实现模型逻辑。

## 目录布局（运行时根）

```text
{bundle_root}/
├── flashcli-bundle.json    # format_version: 3
├── run.py / serve.py       # entry 模块
├── flash_rt/               # FlashRT Python（不含 .so）
└── runtime/<env-key>/       # 本机 env 的 *.so（FlashHub 按环境分包下载）
```

权重不在 bundle 内，由 `weights` 字段声明，缓存在 `~/.flashcli/models/<preset>/`。

## catalog（models.yaml）

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/my_model/1.0.0
      # path: bundles/my_bundle   # 本地开发
```

- **`bundle.repo`** — FlashHub 语义化 API（`/api/v1/repos/{org}/{model}/{version}`），返回 `data.files[]`（`download_url`、`file_size`、`md5_hash`）。
- **`bundle.path`** — 本地 bundle 目录（开发用）。
- **`bundle_variant`** — 多 preset 共享同一 repo 时区分权重（如 Qwen3 / Qwen3.6）。

同 repo 多 preset（如 qwen3 / qwen36）共享 runtime 与 venv，用 `bundle_variant` 区分权重。

## flashcli-bundle.json（v3 必填）

| 字段 | 说明 |
|------|------|
| `format_version: 3` | 唯一支持版本 |
| `description` | bundle 说明（推荐） |
| `python_abi` | bundle 固定 Python ABI（如 `312` = 3.12） |
| `runtime` | `{env_key: path}` — 路径通常为 `runtime/<env-key>/`（含该 env 的 `.so`） |
| `entry` | `run` / `serve` 模块与类 |
| `python_dependencies` | `torch`（可 `{package, index}`）+ `pip` |

环境键：`sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`（PY 来自 `python_abi`）。能力由 `entry` 推断。

## FlashHub 发布

`bash scripts/pack_bundle.sh --bundle-dir bundles/<name>` 产出：

- `dist/flashcli-bundle.json` + `run.py`、`flash_rt/` 等 bundle 源码树
- `dist/runtime/<env-key>/` — 该 env 的 `flash_rt_*.so`

上传整个 `dist/` 到 FlashHub；catalog 填 `bundle.repo` 指向语义化版本 URL（如 `…/repos/flashcli-bundle/pi05_libero/1.0.2`）。

## 运行时流程

1. GET FlashHub 目录 → 下载 `flashcli-bundle.json`
2. preflight：本机 env 是否匹配 `runtime` 中某一 key（可 fuzzy 匹配 sm/cuda）
3. 下载 bundle 源码树 + 本 env 的 `runtime/<env-key>/` 制品
4. 创建 `~/.flashcli/runtimes/<id>/venv`（Python = manifest.python_abi）
5. re-exec：主机 CLI 执行 `bundle_venv/python …/infer_launch.py`（见 [architecture.zh-CN.md](architecture.zh-CN.md)）
6. infer 内 activate bundle → 加载权重 → 调用 `entry`

运行时 layout 校验**只检查本机匹配的 env key**（manifest 里列出的其它 runtime 格不要求已下载）。维护者用 `flashcli bundle validate PATH` 可校验完整矩阵。
