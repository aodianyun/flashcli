# qwen_nvfp4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

一个 **SM120 NVFP4** FlashHub repo；catalog 用 `bundle_variant` 区分 Qwen3-8B 与 Qwen3.6-27B 权重。

## 权重

| variant | 主权重 | MTP（仅 qwen36） |
|---------|--------|------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) 的 `mtp.safetensors` |

要求 **SM120 × cu130 × Python 3.12**（bundle venv）。权重缓存在 `~/.flashcli/models/<preset>/`，不在 bundle 内。

## 运行

命令速查见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**。

```bash
flashcli run qwen3-8b-nvfp4 --prompt "你好"
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 6
```

本地未走 FlashHub：

```bash
flashcli run qwen3-8b-nvfp4 --bundle "$(pwd)/bundles/qwen_nvfp4" --prompt "你好"
```
