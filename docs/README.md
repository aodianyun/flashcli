# flashcli documentation

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

| Document | Audience |
|----------|------------|
| [runtime-matrix.md](runtime-matrix.md) | **Maintainers**: native matrix (`sm` × CUDA × Python ABI), release pipeline, zip naming |
| [environment.md](environment.md) | Environment variables (paths, catalog, HF, switches) |
| [model_bundle_standard.md](model_bundle_standard.md) | Model Bundle format — third-party extenders and maintainers |
| [architecture.md](architecture.md) | Module layout, runtime data flow, **host CLI vs bundle infer** |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | How to contribute + release bundle checklist |
| [../README.md](../README.md) | User quick reference |
| [../bundles/README.md](../bundles/README.md) | Published bundle sources |

**Common commands**: `flashcli models list` · `flashcli models envs [preset]` · `flashcli bundle sync <preset>` · `flashcli bundle validate PATH`

Inference kernels and precision specs live in the [FlashRT](https://github.com/LiangSu8899/FlashRT) repository.
