# flashcli 文档

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

## 按角色阅读

### 终端用户

安装并运行 preset — [../README.zh-CN.md](../README.zh-CN.md)，再读各 bundle [README](../bundles/pi05_libero/README.zh-CN.md)。镜像与缓存：[environment.zh-CN.md](environment.zh-CN.md)。

### 集成方

从 [FlashHub](https://flashhub.top) 固定 preset ref。语法见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

### 对外 Bundle 作者

向 FlashHub 发布 bundle — [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) + [flashcli-bundle/README.md](../flashcli-bundle/README.md)。

### 架构说明（可选）

主机 CLI、bundle venv、sync 流程 — [architecture.zh-CN.md](architecture.zh-CN.md)。维护者模块分层：[module_layers.zh-CN.md](module_layers.zh-CN.md)。

### 维护者（内部）

构建、打包、发布 bundle — [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) · runtime 矩阵 [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)（仅从 [CONTRIBUTING.md](../CONTRIBUTING.md) 索引）。

## 文档索引

| 文档 | 用途 |
|------|------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | manifest、entry、`.so`、FlashHub（权威规范） |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | preset ref 语法 + 运行时流程 |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 主机 CLI、bundle venv、re-exec |
| [environment.zh-CN.md](environment.zh-CN.md) | 环境变量 |
| [module_layers.zh-CN.md](module_layers.zh-CN.md) | 主机 CLI 与 `flashcli_bundle` 包边界 |

各 preset 命令：[bundles/](../bundles/)

**常用命令**：`flashcli models envs [ref]` · `flashcli run <ref> --help`
