# Higgs Audio v3 TTS-4B

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Higgs Audio v3 TTS-4B** zero-shot text-to-speech on FlashRT’s RunEngine (engine mode). Qwen3-4B backbone (FP8 W8A8 / BF16) + fused 8-codebook head + DAC-style codec; outputs 24 kHz mono WAV.

| | |
|---|---|
| **Ref** | `flashcli-bundle/higgs_audio:latest` |
| **Weights** | [bosonai/higgs-audio-v3-tts-4b](https://modelscope.cn/models/bosonai/higgs-audio-v3-tts-4b) (ModelScope) |
| **GPU** | NVIDIA **SM120** (Blackwell; e.g. RTX 5060 Ti / 5090) · CUDA **13.x** |
| **Python** | **3.10** (bundle venv) |
| **Capabilities** | `run` |

**Input:** text to synthesise (`--text`).  
**Output:** 24 kHz mono PCM WAV (`--out`).

Weights are pulled on first `pull` / `run` (not in the bundle zip). Peak VRAM ≈ **6.6 GB** (FP8) / **9.6 GB** (BF16).

## Run

```bash
flashcli pull flashcli-bundle/higgs_audio:latest
flashcli run flashcli-bundle/higgs_audio:latest \
  --text "The quick brown fox jumps over the lazy dog." \
  --out hello.wav
```

Force BF16 (or when FP8 kernels are unavailable):

```bash
flashcli run flashcli-bundle/higgs_audio:latest \
  --fp8 false \
  --text "The quick brown fox jumps over the lazy dog." \
  --out hello.wav
```

Full flags: `flashcli run flashcli-bundle/higgs_audio:latest --help`

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--text` | `The quick brown fox jumps over the lazy dog.` | Text to synthesise |
| `--out` | `output.wav` | Output WAV path (24 kHz mono) |
| `--fp8` | `auto` | Decode precision: `auto` / `true` (FP8) / `false` (BF16) |
| `--device` | `cuda:0` | CUDA device |
| `--max-seq` | `2048` | KV-cache length (prompt + generated frames) |

