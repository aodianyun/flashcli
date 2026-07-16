# Higgs Audio v3 TTS-4B

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Higgs Audio v3 TTS-4B** 零样本文本转语音，基于 FlashRT RunEngine（engine 模式）。Qwen3-4B 骨干（FP8 W8A8 / BF16）+ 8-codebook 融合声学头 + DAC 风格编解码器，输出 24 kHz 单声道 WAV。

| | |
|---|---|
| **Ref** | `flashcli-bundle/higgs_audio:latest` |
| **权重** | [bosonai/higgs-audio-v3-tts-4b](https://modelscope.cn/models/bosonai/higgs-audio-v3-tts-4b)（ModelScope） |
| **GPU** | NVIDIA **SM120**（Blackwell；如 RTX 5060 Ti / 5090）· CUDA **13.x** |
| **Python** | **3.10**（bundle venv） |
| **能力** | `run` |

**输入：** 待合成文本（`--text`）。  
**输出：** 24 kHz 单声道 PCM WAV（`--out`）。

权重在首次 `pull` / `run` 时拉取（不在 bundle zip 内）。FP8 峰值约 **6.6 GB**，BF16 约 **9.6 GB**。

## 运行

```bash
flashcli pull flashcli-bundle/higgs_audio:1.0.0
flashcli run flashcli-bundle/higgs_audio:1.0.0 \
  --text "你好世界，欢迎使用 Higgs Audio。" \
  --out hello.wav
```

强制 BF16（或 FP8 内核不可用时）：

```bash
flashcli run flashcli-bundle/higgs_audio:1.0.0 \
  --fp8 false \
  --text "The quick brown fox jumps over the lazy dog." \
  --out hello.wav
```

完整参数：`flashcli run flashcli-bundle/higgs_audio:1.0.0 --help`

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--text` | `The quick brown fox jumps over the lazy dog.` | 待合成文本 |
| `--out` | `output.wav` | 输出 WAV 路径（24 kHz 单声道） |
| `--fp8` | `auto` | 解码精度：`auto` / `true`（FP8）/ `false`（BF16） |
| `--device` | `cuda:0` | CUDA 设备 |
| `--max-seq` | `2048` | KV 缓存长度（prompt + 生成帧） |

