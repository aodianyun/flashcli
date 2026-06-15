# flashcli Model Bundle（format_version 3）

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

第三方通过 **Model Bundle** 交付推理 runtime。flashcli **仅**加载 bundle 并调用 `entry`，不在 flashcli 源码中实现模型逻辑。

**对外发布标准（目录、manifest、entry、.so 命名、FlashHub 结构）** → **[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)**  

内部维护（编译、打包、flashcli 命令）→ [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md)；公开 catalog：[models.yaml](../src/flashcli/catalog/models.yaml)。

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
      repo: https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/my_model:1.0.0
      # path: bundles/my_bundle   # 本地开发
    # bundle_variant: qwen3        # 多 preset 共用同一 repo 时
```

- **`bundle.repo`** — FlashHub 语义化 API。catalog 使用 `flashhub-api.aodianyun.com`，版本写为 `model:version`（冒号）。返回 `data.files[]`（`download_url`、`file_size`、`md5_hash`）。
- **`bundle.path`** — 本地 bundle 目录（开发用）。
- **`bundle_variant`** — 多 preset 共享同一 repo 时区分权重（如 Qwen3 / Qwen3.6）。

## flashcli-bundle.json（v3）

| 字段 | 说明 |
|------|------|
| `format_version: 3` | 唯一支持的 manifest schema 版本 |
| `protocol_version: 1` | **flashcli-bundle** API 版本（**必填**；须与已安装的 `flashcli-bundle` 一致） |
| `name` | bundle 标识 |
| `description` | bundle 说明（推荐） |
| `python_abi` | bundle 固定 Python ABI（如 `312` = 3.12） |
| `runtime` | `{env_key: path}` — 通常为 `runtime/<env-key>/` |
| `entry` | `run` / `serve` 模块与类 |
| `python_dependencies` | `torch`（可 `{package, index}`）+ `pip` |
| `run_options` | `flashcli run` 的 bundle 参数 |
| `serve_options` | `flashcli serve` 的 bundle 参数 |
| `variants` | 多 preset 共用 repo 时的分 variant 配置 |

环境键：`sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`（PY 来自 `python_abi`）。能力由 `entry` 推断。

### PyTorch wheel index

推荐 `"index": "auto"`：flashcli 根据本机匹配的 runtime env key 选择 `cu124` 或 `cu128`（SM89 cu124 → cu124；SM120 / cu130 → cu128）。除非 bundle 只支持单一 CUDA 线，否则不要写死 `cu128`。

### run_options / serve_options

Bundle 自定义参数在 manifest 中声明；flashcli 据此生成 `--help` 并解析 argv。默认值写在各 option 的 `"default"` 字段（**没有**顶层 `defaults` 块）。

| 命令 | manifest 键 | 传入 engine 的阶段 |
|------|-------------|-------------------|
| `flashcli run` | `run_options` | `load` → `load()`；`predict` → `predict()` |
| `flashcli serve` | `serve_options` | `load` → `load()`；`warmup` → warmup |

每个 option：

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Python 关键字参数名（snake_case） |
| `type` | 否 | `string`（默认）、`integer`、`float`、`boolean` |
| `default` | 否 | 省略 flag 时的默认值 |
| `help` | 是 | 出现在 `--help` 中 |
| `phase` | 否 | run：`load` / `predict`；serve：`load` / `warmup` |
| `flag` | 否 | CLI 名（不含 `--`；默认 `_` 转 `-`） |

**flashcli 内置参数**（不在 manifest）：run 的 `--bundle`、`--checkpoint`、`--benchmark` 等；serve 的 `--host`、`--port` 等。

```bash
flashcli run pi05_libero --help
flashcli serve qwen3-8b-nvfp4 --help
```

### variants（多 preset 共用 repo）

存在 `variants` 时，**每个 variant 必须各自定义** `run_options` / `serve_options`（与 `entry` 对应）。顶层 `run_options` / `serve_options` **禁止**，校验会报错。

catalog 中多个 preset 指向同一 `bundle.repo`，用 `bundle_variant` 区分权重。

variant 块常见字段：`description`、`weights`、`weights_dir`、`extra_weights`、`env`、`run_options`、`serve_options`。

完整 manifest 示例见 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) §3.8 与仓库内 `bundles/pi05_libero/flashcli-bundle.json`、`bundles/qwen_nvfp4/flashcli-bundle.json`。

## FlashHub 发布

`bash scripts/pack_bundle.sh --bundle-dir bundles/<name>` 产出 `dist/`：`flashcli-bundle.json`、entry 源码、`runtime/<env-key>/`。

打包脚本会根据 `lib/*.so` 刷新 manifest 的 `runtime` 映射，**不会**删除 `run_options` / `serve_options`。

上传整个 `dist/` 到 FlashHub；catalog 填 `bundle.repo` 指向语义化版本 URL。

## 运行时流程

1. GET FlashHub 目录 → 下载 `flashcli-bundle.json`
2. preflight：本机 env 是否匹配 `runtime` 中某一 key
3. 下载 bundle 源码树 + 本 env 的 `runtime/<env-key>/`
4. 创建 bundle venv（Python = `python_abi`）
5. re-exec：`infer_launch.py`（见 [architecture.zh-CN.md](architecture.zh-CN.md)）
6. activate → 加载权重 → 调用 `entry`

运行时 layout 校验**只检查本机匹配的 env key**。维护者用 `flashcli bundle validate PATH` 校验完整矩阵。

## entry 约定

- `entry.*.module` 相对 bundle 根目录，在 `PYTHONPATH` 上。
- 实现 `RunEngine` / `ServeEngine`。
- bundle 内通过 **`flashcli_bundle`**（pip 包 `flashcli-bundle`）的 `run_option_defaults()` / `serve_option_defaults()` / `option_value()` 读取 manifest 默认值。**不要**在 `run.py` / `serve.py` 里写死与 manifest 重复的默认值。
- 推理逻辑全部在 bundle 内。

## 校验

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --help
flashcli serve qwen3-8b-nvfp4 --help
```
