# flashcli 文档

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

本目录包含用户、集成方和维护者文档。先读根目录 [README](../README.zh-CN.md) 完成安装与
`run`/`serve`；下表列出每个文档的受众与内容。

## 文档清单

| 文档 | 受众 | 内容 |
|------|------|------|
| [../README.zh-CN.md](../README.zh-CN.md) | 用户 | 安装、`run`/`serve`、更新动态、文档入口 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献者 | 仓库结构、开发环境、二进制/桌面构建、Git 流程、发布清单与说明规范 |
| [flashserver.zh-CN.md](flashserver.zh-CN.md) | 用户 / 集成方 | `flashserver`、`flashserver-setup`、桌面客户端：安装、API、启动参数、生命周期、排障 |
| [openapi.yaml](openapi.yaml) | 集成方 | **权威** HTTP 契约（也通过 `/openapi.yaml` 提供） |
| [environment.zh-CN.md](environment.zh-CN.md) | 用户 | Go host 读取的环境变量、镜像、缓存路径 |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | 集成方 | preset ref 语法 + 终端用户运行时流程 |
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | bundle 作者 | **权威** manifest、entry、`.so`、FlashHub 布局 |
| [app_manifest_standard.zh-CN.md](app_manifest_standard.zh-CN.md) | 应用作者 / 集成方 | **权威** FlashHub 应用 manifest（v1）：字段、安装命令、默认 bundle |
| [application_install_plan.zh-CN.md](application_install_plan.zh-CN.md) | 维护者 | `flashcli app` 安装流程、状态机、回滚、命令、里程碑 |
| [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) | bundle 作者 | `entry.kind` 后端、原生进程/`.so` 契约、conformance |
| [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) | bundle 作者 | **权威** OpenAI/Anthropic serve 对接：能力、`ServeEngine`、端点输入输出 |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 贡献者 | 运行时流程、本地服务栈、host 与 bundle、缓存、目录布局 |
| [module_layers.zh-CN.md](module_layers.zh-CN.md) | 贡献者 | host / infer / protocol 归属与 Go 包地图 |
| [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) | 维护者 | bundle 构建、多 CUDA 矩阵发布、FlashHub 上传 |
| [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md) | 维护者 | SM × CUDA × Python 发布矩阵 |

各 bundle 的命令、参数与构建文档：[`bundles/`](../bundles/README.zh-CN.md)。
英文文档使用同名文件（去掉 `.zh-CN` 后缀）。

## 阅读路径

- **终端用户** —— 根 README（安装、`run`/`serve`）→ [FlashHub](https://flashhub.top)
  上对应的 bundle 页面（ref、模型参数）→ [environment.zh-CN.md](environment.zh-CN.md)
  （镜像与缓存位置）。
- **本地服务用户** —— 根 README → [flashserver.zh-CN.md](flashserver.zh-CN.md)
  （安装包、桌面客户端、API、启动参数）→ 集成时读 [openapi.yaml](openapi.yaml)。
- **集成方** —— [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)（ref）→
  [openapi.yaml](openapi.yaml)（HTTP）→ [environment.zh-CN.md](environment.zh-CN.md)。
- **bundle 作者** —— [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) →
  [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) →
  [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)（LLM/音频/图像/视频 serve）→
  [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md)。
- **维护者 / 贡献者** —— [architecture.zh-CN.md](architecture.zh-CN.md) →
  [module_layers.zh-CN.md](module_layers.zh-CN.md) → [../CONTRIBUTING.md](../CONTRIBUTING.md)。
