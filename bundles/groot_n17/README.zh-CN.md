# GROOT N1.7

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**NVIDIA GR00T N1.7** 是面向通用机器人策略的**视觉–语言–动作（VLA）**基础模型。本 preset 在 **FlashRT** 上运行 **3B** 权重 [`nvidia/GR00T-N1.7-3B`](https://huggingface.co/nvidia/GR00T-N1.7-3B)，采用 N1.7 契约：先用 bundle 内 vendoring 的 **Isaac-GR00T** `Gr00tPolicy`（`gr00t/`，无需 pip 安装）从图像与 prompt 合成 `aux`，再经 FlashRT 的 `set_prompt` + `infer` 输出动作。

| | |
|---|---|
| **Ref** | `flashcli-bundle/groot_n17:1.0.0` |
| **权重** | [nvidia/GR00T-N1.7-3B](https://huggingface.co/nvidia/GR00T-N1.7-3B) |
| **GPU** | NVIDIA **SM120**（Blackwell）· CUDA **13.x** |
| **Python** | **3.10**（bundle venv；Isaac-GR00T 官方要求） |
| **能力** | `run` |

**输入：** 任务 prompt + 一路或多路 RGB 图像（默认零状态；可选 `--state` npz）。  
**输出：** 按 embodiment 模态反归一化后的动作字典（如 `eef_9d`、`joint_position`）。

**常用 embodiment tag**（完整列表见 `flash_rt/models/groot_n17/embodiments.py`）：

| Tag | 路数 | 说明 |
|-----|------|------|
| `oxe_droid_relative_eef_relative_joint`（默认） | 2 | OXE Droid 相对 EEF + 关节 |
| `gr1_unified` | 2 | 人形 GR-1 unified |
| `libero_sim` | 2 | LIBERO 仿真 |
| `simpler_env_google` | 1 | SimplerEnv Google 机器人 |

`--num-views` 须与 tag 一致。建议使用真实图像；占位帧仅用于冒烟。

首次运行自动拉取权重（checkpoint 自包含 Qwen3-VL，无需独立 tokenizer 侧车）。

## 运行

```bash
flashcli run flashcli-bundle/groot_n17:1.0.0 \
  --prompt "put the blue block in the green bowl" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --image /path/v0.jpg,/path/v1.jpg
```

无图像冒烟（占位帧 + 零状态）：

```bash
flashcli run flashcli-bundle/groot_n17:1.0.0 \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2
```

完整参数：`flashcli run flashcli-bundle/groot_n17:1.0.0 --help`

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `put the blue block in the green bowl` | 任务指令 |
| `--image` | — | 逗号分隔 RGB 路径 |
| `--state` | — | 可选 `.npz`（`state.*` 键）用于归一化与相对动作解码 |
| `--embodiment-tag` | `oxe_droid_relative_eef_relative_joint` | 策略槽位 |
| `--num-views` | `2` | 须与 embodiment 一致 |
| `--action-horizon` | `40` | 动作步数 |
| `--hardware` | `auto` | FlashRT 后端 |
| `--autotune` | `3` | CUDA graph 调优 |
| `--use-fp8` | 开启 | FP8 权重 |
| `--use-fp16` | 关闭 | 全 FP16 基线 |
| `--config` | `groot_n17` | FlashRT 配置名 |
| `--seed` | `0` | Gr00tPolicy aux 捕获 RNG 种子 |
