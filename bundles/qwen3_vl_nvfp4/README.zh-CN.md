# qwen3_vl_nvfp4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

**Qwen3-VL-8B NVFP4** 多模态 bundle — 图文 `run` 与 OpenAI 兼容 `serve`（真流式 SSE、tool calls）。

## 结构

`format_version: 3` manifest，`runtime: { env_key: path }`。FlashHub sync 后 native `.so` 在 `runtime/<env-key>/`。要求 **SM120 × cu130 × Python 3.12**（bundle venv）。权重不在 bundle 内，需拉取 FlashRT NVFP4 格式 checkpoint。

| 组件 | 说明 |
|------|------|
| `flash_rt_kernels` | NVFP4 语言 GEMM（SM120） |
| `flash_rt_fa2` | FA2 attention |
| `flash_rt_qwen3_vl_kernels` | 视觉塔 + 多模态 scatter |
| Bundle 引擎 | `_engine_qwen3_vl.py`（非 FlashRT examples） |

## 权重

运行时需要 **FlashRT NVFP4** checkpoint（非 BF16 源权重 `Qwen/Qwen3-VL-8B-Instruct`）。维护者：运行 [`scripts/prepare_qwen3_vl_weights.sh`](scripts/prepare_qwen3_vl_weights.sh)，上传 HF 后更新 `weights.repo`。开发：`quantize` 后 `--embed-checkpoint`。

## 使用

详见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**。

```bash
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg --prompt "描述这张图" --max-tokens 128

flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --host 0.0.0.0 --port 8000 --max-pixels 500000
```

本地 bundle：

```bash
flashcli run bundles/qwen3_vl_nvfp4 --image scene.jpg --prompt "描述这张图"
```

## 边界（v1）

- 支持：图片 / `image_url`、流式 SSE、EOS、采样、tools / `tool_calls`
- 不支持：thinking / `reasoning_content`、视频

**16GB 显存建议：** `--max-pixels 500000`、`--max-seq 2048`。
