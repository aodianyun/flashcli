# Model Bundle — preset ref 与运行时流程

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

面向 **集成方** 对接 preset 与 FlashHub。manifest、entry、`.so` 完整规范 → **[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)**。

## Preset ref（FlashHub）

用户使用 **ref 字符串**，不再依赖内置 catalog 文件：

```text
namespace/bundle:version[@variant]
```

示例：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36
```

| 部分 | 含义 |
|------|------|
| `namespace/bundle:version` | FlashHub repo 名 + 固定版本 |
| `@variant` | 可选；选择 manifest `variants.*`（如 Qwen3 / Qwen3.6） |
| 完整 URL | `https://flashhub-api…/flashcli-bundle/pi05_libero:1.0.3` 也可 |

**API 基址**（环境变量）：`FLASHCLI_FLASHHUB_API`（默认 `https://flashhub-api.aodianyun.com/api/v1/repos`）。  
拼出 repo URL：`{FLASHCLI_FLASHHUB_API}/{namespace}/{bundle}:{version}`。

**本地开发**（positional，路径下须有 `flashcli-bundle.json`）：

```bash
flashcli run bundles/qwen_nvfp4@qwen36
flashcli pull bundles/qwen_nvfp4@qwen36
```

多 variant bundle 的 ref **必须**带 `@variant`。

## sync 后目录

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<env-key>/
```

权重不在 bundle 内，缓存在 `~/.flashcli/models/<bundle>/<version>@<variant>/`。

## 终端用户运行时流程

1. 解析 REF → 若为本地目录则用 `local_root`；否则 `bundle.repo`（或已 sync 的 marker）
2. FlashHub manifest → 本机 **preflight** env key
3. 下载 entry + 匹配的 `runtime/<env-key>/`
4. 创建 bundle venv
5. 在 bundle venv 内 **re-exec** infer — [architecture.zh-CN.md](architecture.zh-CN.md)
6. activate → HF 权重 → `entry`

`flashcli bundle sync <ref>` 可预拉；首次 `run` / `serve` 会自动 sync。

**环境键**（`flashcli models envs <ref>`）：`sm{SM}-cu{CUDA}-linux-x86_64-py{PY}`。

## 快速校验

```bash
flashcli models list          # 仅显示本地已缓存 ref
flashcli models envs <ref>
flashcli bundle validate /path/to/bundle
flashcli run <ref> --help
```
