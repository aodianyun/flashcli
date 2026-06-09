# flashcli 运行包方案（已实施）

<p align="right"><a href="runtime-package-schemes.md">English</a></p>

**当前实现（format_version 3）：**

| 能力 | 实现 |
|------|------|
| manifest-first | FlashHub 语义化 repo API（如 `…/repos/flashcli-bundle/pi05_libero/1.0.2`）→ 先拉 `flashcli-bundle.json` → preflight |
| 分包下载 | FlashHub repo 源码树 + 本 env 的 `runtime/<env-key>/` |
| 单 Python ABI | `python_abi` 固定；bundle venv 使用该版本 |
| 依赖隔离 | `~/.flashcli/runtimes/<id>/venv/` 每 bundle 独立 |
| 推理进程 | CLI venv 准备 runtime 后 **re-exec** 进 bundle venv |

详见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。
