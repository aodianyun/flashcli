# Model Bundle — catalog 与运行时流程

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

面向 **catalog 集成方** 对接 preset 与 FlashHub。manifest、entry、`.so` 完整规范 → **[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)**。

## catalog（models.yaml）

源文件：[`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/my_model:1.0.0
      # path: bundles/my_bundle   # 本地开发
    # bundle_variant: qwen3        # 多 preset 共用同一 repo
```

| 字段 | 用途 |
|------|------|
| `bundle.repo` | FlashHub API（`flashhub-api…`，`model:version`），返回 `data.files[]` 供分包下载。 |
| `bundle.path` | 本地 bundle 目录（仅开发）。 |
| `bundle_variant` | 同一 repo 多 preset 时选择 manifest `variants.*`（如 Qwen3 / Qwen3.6）。 |

## sync 后目录

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<env-key>/      # FlashHub sync 后；运行时直接从此目录加载 .so
```

权重不在 bundle 内，缓存在 `~/.flashcli/models/<preset>/`。

## 终端用户运行时流程

1. 解析 preset → `bundle.repo`（或 `--bundle` / `path`）
2. FlashHub 拉 manifest → **preflight** 本机 env key
3. 下载 entry 源码树 + **仅**本 env 的 `runtime/<env-key>/`
4. 创建 bundle venv（`python_abi`、manifest 中的 torch）
5. 在 bundle venv 内 **re-exec** infer（主机 flashcli 经 `PYTHONPATH`）— [architecture.zh-CN.md](architecture.zh-CN.md)
6. activate → HF 权重 → `entry`

`flashcli bundle sync <preset>` 可预拉；首次 `run` / `serve` 会自动执行。

**环境键**（用 `flashcli models envs <preset>` 查看）：`sm{SM}-cu{CUDA}-linux-x86_64-py{PY}`，例如 `sm89-cu124-linux-x86_64-py312`、`sm120-cu130-linux-x86_64-py312`。`PY` 与 manifest `python_abi` 一致（当前为 `312`）。

## 快速校验

```bash
flashcli models envs <preset>
flashcli bundle validate /path/to/bundle
flashcli run <preset> --help
```
