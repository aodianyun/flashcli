# Qwen3-VL NVFP4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Qwen3-VL-8B** 多模态模型，FlashRT NVFP4 格式。支持图文 `run` 与 OpenAI 兼容 `serve`（SSE 流式、工具调用）。

| | |
|---|---|
| **Ref** | `flashcli-bundle/qwen3_vl_nvfp4:1.0.0` |
| **权重** | [cpadyun/Qwen3-VL-8B-FlashRT-NVFP4](https://huggingface.co/cpadyun/Qwen3-VL-8B-FlashRT-NVFP4)（FlashRT NVFP4 checkpoint） |
| **Processor** | [Qwen/Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) |
| **GPU** | NVIDIA **SM120** · CUDA **13.x** |
| **Python** | **3.12**（bundle venv） |
| **能力** | `run`、`serve` |

**支持：** `image` / `image_url`、SSE 流式、采样、tools / `tool_calls`  
**不支持（v1）：** thinking / `reasoning_content`、视频

## 运行

```bash
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg \
  --prompt "用一句话描述这张图。" \
  --max-tokens 128
```

## 服务

```bash
flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --host 0.0.0.0 --port 8000 \
  --max-pixels 500000
```

完整参数：`flashcli run … --help` · `flashcli serve … --help`

## 参数

### `run`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `Hello!` | 用户消息 |
| `--image` | — | 图片路径、URL 或 base64 data URL |
| `--max-tokens` | `256` | 最大生成 token |
| `--max-pixels` | `500000` | 限制图像分辨率（显存 / 首 token 延迟） |
| `--max-seq` | `2048` | 上下文长度 |
| `--max-q-seq` | `1024` | 最大 prefill（文本 + 视觉 token） |
| `--temperature` | `0.0` | 采样温度 |
| `--top-p` | `1.0` | Nucleus 采样 |
| `--top-k` | `0` | Top-k（`0` 关闭） |

### `serve`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--model-name` | `qwen3-vl` | OpenAI `model` 字段 |
| `--max-seq` | `2048` | 上下文长度 |
| `--max-pixels` | `500000` | 图像分辨率上限 |
| `--warmup-preset` | `none` | `short` = 用占位图预热 decode 图 |
