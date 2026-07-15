# Wan2.2 TI2V-5B

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Wan2.2-TI2V-5B** text/image-to-video on FlashRT’s official pipeline (`config="wan22_ti2v_5b"`). Generate an MP4 from a text prompt (`t2v`) or from a start image plus prompt (`i2v`).

| | |
|---|---|
| **Ref** | `flashcli-bundle/wan22:1.0.0` |
| **Weights** | [Wan-AI/Wan2.2-TI2V-5B](https://www.modelscope.cn/models/Wan-AI/Wan2.2-TI2V-5B) (ModelScope, ~34 GB) |
| **GPU** | NVIDIA **SM120** (Blackwell; e.g. RTX 5060 Ti / 5090) · CUDA **13.x** |
| **Python** | **3.10** (bundle venv) |
| **Capabilities** | `run` |

**Inputs:** text prompt (`t2v`); or prompt + start image (`i2v`).  
**Output:** MP4 video (`--out`).

Defaults target **16 GB** (5060 Ti: 832×480, 81 frames, `--offload-model true`). Scale resolution/frames on larger VRAM. Weights are pulled on first `pull` / `run` (not in the bundle zip). No `flash_attn` wheel is required.

## Run

Text-to-video (5060 Ti baseline):

```bash
flashcli run flashcli-bundle/wan22:1.0.0 \
  --prompt "A cinematic shot of a blue sphere rolling across a wooden table"
```

Smoke test (few frames / steps):

```bash
PYTHONUNBUFFERED=1 flashcli run flashcli-bundle/wan22:1.0.0 \
  --frames 5 --steps 2 --out smoke.mp4
```

RTX 5090 (32 GB) — FlashRT official 720p baseline (`1280×704`, 121 frames, `steps=20`).
Keep `--offload-model true` (FlashRT API default; published peak ~**24.4 GiB**). Setting `false` can OOM in VAE decode when DiT stays resident.

```bash
# Quality baseline (~179 s, TeaCache off)
flashcli run flashcli-bundle/wan22:1.0.0 \
  --width 1280 --height 704 --frames 121 --steps 20 \
  --shift 5.0 --guide-scale 5.0 \
  --offload-model true

# TeaCache 0.3 (~114 s / ~1.56×; may change composition on some prompts)
flashcli run flashcli-bundle/wan22:1.0.0 \
  --width 1280 --height 704 --frames 121 --steps 20 \
  --shift 5.0 --guide-scale 5.0 \
  --offload-model true \
  --teacache --teacache-threshold 0.3
```

Image-to-video:

```bash
flashcli run flashcli-bundle/wan22:1.0.0 \
  --mode i2v \
  --image /path/start.png \
  --frames 81
```

Full flags: `flashcli run flashcli-bundle/wan22:1.0.0 --help`

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `A cinematic shot of a blue sphere rolling across a wooden table` | Text prompt |
| `--negative-prompt` | *(pipeline default)* | Negative prompt |
| `--mode` | `t2v` | `t2v` or `i2v` |
| `--image` | — | Start image path (`i2v` only) |
| `--width` / `--height` | `832` / `480` | Output size (multiples of 32; 5090: `1280` / `704`) |
| `--frames` | `81` | Frame count (**must be `4n+1`**; 5090: `121`) |
| `--steps` | `20` | Flow-matching denoise steps |
| `--shift` | `5.0` | Sampler shift |
| `--guide-scale` | `5.0` | Classifier-free guidance |
| `--seed` | `1234` | RNG seed |
| `--sample-solver` | `unipc` | Sampling solver |
| `--offload-model` | `true` | CPU/GPU stage offload — keep `true` for 16 GB and for 5090 720p (matches FlashRT) |
| `--teacache` | off | TeaCache step-skipping |
| `--teacache-threshold` | `0.0` | Typical `0.15`–`0.30` when TeaCache is on |
| `--out` | `wan22_out.mp4` | Output MP4 path |
| `--hardware` | `auto` | FlashRT backend (`rtx_sm120`, …) |

| Preset | Resolution | Frames | `--offload-model` |
|--------|------------|--------|-------------------|
| 5060 Ti (16 GB) | 832×480 | 81 | `true` |
| 5090 (32 GB) | 1280×704 | 121 | `true` |
