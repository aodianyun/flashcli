# Pi0.5 LIBERO

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Pi0.5** 视觉–语言–动作（VLA）策略，在 LIBERO 操作任务上微调。根据自然语言指令与相机图像输出机器人动作，适用于桌面抓取、放置等操作。

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero:1.0.4` |
| **权重** | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)（约 7.5 GB） |
| **GPU** | NVIDIA **SM89**（Ada）或 **SM120**（Blackwell） |
| **CUDA** | **12.4+**（SM89）· **13.x**（SM120） |
| **Python** | **3.12**（bundle venv） |
| **能力** | `run` |

**输入：** 任务 prompt + RGB 图像（LIBERO 默认 **2** 路相机）。  
**输出：** 机器人策略动作序列。

权重与 PaliGemma tokenizer 在首次运行时自动拉取（不在 bundle zip 内）。

## 运行

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

双路相机（逗号分隔路径）：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --num-views 2 \
  --image /path/view0.jpg,/path/view1.jpg
```

使用本地 checkpoint：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --checkpoint /path/to/checkpoint \
  --image /path/to/base.jpg
```

完整参数：`flashcli run flashcli-bundle/pi05_libero:1.0.4 --help`

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `pick up the red block and place it in the tray` | 任务指令 |
| `--image` | — | 逗号分隔的 RGB 路径（每路相机一张） |
| `--num-views` | `2` | 相机路数 |
| `--hardware` | `auto` | FlashRT 后端 |
| `--autotune` | `3` | CUDA graph 调优次数（`0` 关闭） |
| `--use-fp8` | 开启 | 支持时使用 FP8 权重 |
| `--config` | `pi05` | FlashRT 配置名 |
| `--checkpoint` | *（自动）* | 覆盖缓存权重目录 |
