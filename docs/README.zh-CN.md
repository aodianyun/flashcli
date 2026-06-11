# flashcli 文档

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

| 文档 | 读者 |
|------|------|
| [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md) | **维护者**：原生矩阵（sm × CUDA × Python ABI）、发布流水线、zip 命名 |
| [environment.zh-CN.md](environment.zh-CN.md) | 环境变量（路径、catalog、HF、开关） |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | Model Bundle 格式 — 第三方扩展与维护 |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 模块划分、运行时数据流、**主机 CLI 与 bundle infer** |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献指南（英文）+ 发布 checklist |
| [../README.zh-CN.md](../README.zh-CN.md) | 用户速查 |
| [../bundles/README.zh-CN.md](../bundles/README.zh-CN.md) | 已发布 bundle 源码 |

**常用命令**：`flashcli models list` · `flashcli models envs [preset]` · `flashcli bundle sync <preset>` · `flashcli bundle validate PATH`

推理内核与精度说明请参阅 [FlashRT](https://github.com/LiangSu8899/FlashRT) 仓库。
