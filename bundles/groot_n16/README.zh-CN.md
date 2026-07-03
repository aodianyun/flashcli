# GROOT N1.6

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**NVIDIA GR00T N1.6** 是面向通用机器人策略的**视觉–语言–动作（VLA）**基础模型。本 preset 在 **FlashRT** 上运行 **3B** 权重 [`nvidia/GR00T-N1.6-3B`](https://huggingface.co/nvidia/GR00T-N1.6-3B)，根据自然语言任务与相机图像输出多步机器人动作。

| | |
|---|---|
| **Ref** | `flashcli-bundle/groot_n16:1.0.0` |
| **权重** | [nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B) |
| **GPU** | NVIDIA **SM120**（Blackwell）· CUDA **13.x** |
| **Python** | **3.12**（bundle venv） |
| **能力** | `run` |

**输入：** 任务 prompt + 一路或多路 RGB 图像。  
**输出：** 动作序列（随 embodiment 为关节或末端位姿等）。

**已训练的 embodiment tag：**

| Tag | 路数 | 机器人 |
|-----|------|--------|
| `gr1`（默认） | 1 | 人形 GR-1 |
| `robocasa_panda_omron` | 3 | RoboCasa + Panda |
| `behavior_r1_pro` | 3 | BEHAVIOR R1 Pro |

`--num-views` 须与 tag 一致，否则输出常无意义。

首次运行自动拉取权重与 Qwen3 tokenizer（不在 bundle zip 内）。

## 运行

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg
```

无图像冒烟（占位帧）：

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --embodiment-tag gr1 \
  --num-views 1
```

三路相机：

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --prompt "open the drawer" \
  --embodiment-tag robocasa_panda_omron \
  --num-views 3 \
  --image /path/v0.jpg,/path/v1.jpg,/path/v2.jpg
```

完整参数：`flashcli run flashcli-bundle/groot_n16:1.0.0 --help`

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `pick up the cup on the table` | 任务指令 |
| `--image` | — | 逗号分隔 RGB 路径 |
| `--embodiment-tag` | `gr1` | 策略槽位 |
| `--num-views` | `1` | 须与 embodiment 一致 |
| `--action-horizon` | `16` | 动作步数（完整 horizon 用 `50`） |
| `--hardware` | `auto` | FlashRT 后端 |
| `--autotune` | `3` | CUDA graph 调优 |
| `--use-fp8` | 开启 | FP8 权重 |
| `--use-fp16` | 关闭 | 全 FP16 基线 |
| `--config` | `groot` | FlashRT 配置名 |
