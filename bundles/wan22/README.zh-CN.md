# Wan2.2 TI2V-5B

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Wan2.2-TI2V-5B** 文本/图像生成视频，基于 FlashRT 官方管线（`config="wan22_ti2v_5b"`）。支持纯文本生成（`t2v`），或起始图像 + 文本生成（`i2v`），输出 MP4。

| | |
|---|---|
| **Ref** | `flashcli-bundle/wan22:1.0.0` |
| **权重** | [Wan-AI/Wan2.2-TI2V-5B](https://www.modelscope.cn/models/Wan-AI/Wan2.2-TI2V-5B)（ModelScope，约 34 GB） |
| **GPU** | NVIDIA **SM120**（Blackwell；如 RTX 5060 Ti / 5090）· CUDA **13.x** |
| **Python** | **3.10**（bundle venv） |
| **能力** | `run` |

**输入：** 文本 prompt（`t2v`）；或 prompt + 起始图像（`i2v`）。  
**输出：** MP4 视频（`--out`）。

默认面向 **16 GB** 显存（5060 Ti：832×480、81 帧、`--offload-model true`）。更大显存可上调分辨率/帧数。权重在首次 `pull` / `run` 时拉取（不在 bundle zip 内）。无需安装 `flash_attn` wheel。

## 运行

文本生成视频（5060 Ti 基线）：

```bash
flashcli run flashcli-bundle/wan22:1.0.0 \
  --prompt "A cinematic shot of a blue sphere rolling across a wooden table"
```

冒烟测试（少帧 / 少步）：

```bash
PYTHONUNBUFFERED=1 flashcli run flashcli-bundle/wan22:1.0.0 \
  --frames 5 --steps 2 --out smoke.mp4
```

RTX 5090（32 GB）—— FlashRT 官方 720p 基线（`1280×704`、121 帧、`steps=20`）。
保持 `--offload-model true`（FlashRT API 默认；公布峰值约 **24.4 GiB**）。设为 `false` 时 DiT 常驻，VAE decode 阶段容易 OOM。

```bash
# 画质基线（约 179 s，无 TeaCache）
flashcli run flashcli-bundle/wan22:1.0.0 \
  --width 1280 --height 704 --frames 121 --steps 20 \
  --shift 5.0 --guide-scale 5.0 \
  --offload-model true

# TeaCache 0.3（约 114 s / ~1.56×；部分 prompt 可能有构图漂移）
flashcli run flashcli-bundle/wan22:1.0.0 \
  --width 1280 --height 704 --frames 121 --steps 20 \
  --shift 5.0 --guide-scale 5.0 \
  --offload-model true \
  --teacache --teacache-threshold 0.3
```

图像生成视频：

```bash
flashcli run flashcli-bundle/wan22:1.0.0 \
  --mode i2v \
  --image /path/start.png \
  --frames 81
```

完整参数：`flashcli run flashcli-bundle/wan22:1.0.0 --help`

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `A cinematic shot of a blue sphere rolling across a wooden table` | 文本提示 |
| `--negative-prompt` | *（管线默认）* | 负面提示 |
| `--mode` | `t2v` | `t2v` 或 `i2v` |
| `--image` | — | 起始图像路径（仅 `i2v`） |
| `--width` / `--height` | `832` / `480` | 输出分辨率（32 的倍数；5090：`1280` / `704`） |
| `--frames` | `81` | 帧数（**须满足 `4n+1`**；5090：`121`） |
| `--steps` | `20` | Flow-matching 去噪步数 |
| `--shift` | `5.0` | Sampler shift |
| `--guide-scale` | `5.0` | CFG 引导强度 |
| `--seed` | `1234` | 随机种子 |
| `--sample-solver` | `unipc` | 采样求解器 |
| `--offload-model` | `true` | CPU/GPU 分阶段卸载 —— 16 GB 与 5090 720p 均保持 `true`（对齐 FlashRT） |
| `--teacache` | 关闭 | TeaCache 跳步加速 |
| `--teacache-threshold` | `0.0` | 开启 TeaCache 时常用 `0.15`–`0.30` |
| `--out` | `wan22_out.mp4` | 输出 MP4 路径 |
| `--hardware` | `auto` | FlashRT 后端（`rtx_sm120` 等） |

| 预设 | 分辨率 | 帧数 | `--offload-model` |
|------|--------|------|-------------------|
| 5060 Ti（16 GB） | 832×480 | 81 | `true` |
| 5090（32 GB） | 1280×704 | 121 | `true` |
