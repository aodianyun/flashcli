# flashcli 文档

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

## 按角色阅读

- **终端用户** — 安装并运行 preset：[../README.zh-CN.md](../README.zh-CN.md)，再读各 bundle [README](../bundles/README.zh-CN.md)。镜像与缓存：[environment.zh-CN.md](environment.zh-CN.md)。
- **集成方** — 从 [FlashHub](https://flashhub.top) 固定 preset ref：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。
- **对外 Bundle 作者** — 发布到 FlashHub：[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)（+ [flashcli-bundle/README.md](../flashcli-bundle/README.md)）；执行后端：[bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。
- **维护者** — 构建/发布 bundle：[bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) · [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)。
- **贡献者 / 架构** — [architecture.zh-CN.md](architecture.zh-CN.md)、[module_layers.zh-CN.md](module_layers.zh-CN.md)；规则见 [../CONTRIBUTING.md](../CONTRIBUTING.md)。

## 文档索引

| 文档 | 受众 | 用途 |
|------|------|------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | 外部作者 | **权威**：manifest、entry、`.so`、FlashHub 布局 |
| [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) | 外部作者 | `entry.kind` 后端、原生进程/`.so` 契约、conformance |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | 集成方 | preset ref 语法 + 运行时流程 |
| [environment.zh-CN.md](environment.zh-CN.md) | 用户 | 环境变量、镜像、缓存路径 |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 贡献者 | 运行时流程、核心原则、host 与 bundle |
| [module_layers.zh-CN.md](module_layers.zh-CN.md) | 贡献者 | host / infer / protocol 包边界 |
| [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) | 维护者 | 构建、矩阵发布、FlashHub 上传 |
| [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md) | 维护者 | SM × CUDA × Python 发布矩阵 |

各 bundle 命令与构建文档：[`bundles/`](../bundles/README.zh-CN.md)。
