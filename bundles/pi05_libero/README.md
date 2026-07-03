# Pi0.5 LIBERO

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Pi0.5** vision–language–action (VLA) policy fine-tuned on LIBERO manipulation tasks. Given a natural-language instruction and camera images, the model outputs robot actions for tabletop pick-and-place style tasks.

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero:1.0.4` |
| **Weights** | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) (~7.5 GB) |
| **GPU** | NVIDIA **SM89** (Ada) or **SM120** (Blackwell) |
| **CUDA** | **12.4+** (SM89) · **13.x** (SM120) |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run` |

**Inputs:** task prompt + RGB images (LIBERO uses **2** camera views by default).  
**Output:** action sequence for the robot policy.

Weights and a PaliGemma tokenizer file are pulled on first run (not in the bundle zip).

## Run

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

Two views (comma-separated paths):

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --num-views 2 \
  --image /path/view0.jpg,/path/view1.jpg
```

Use a local checkpoint directory:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --checkpoint /path/to/checkpoint \
  --image /path/to/base.jpg
```

Full flag list: `flashcli run flashcli-bundle/pi05_libero:1.0.4 --help`

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `pick up the red block and place it in the tray` | Task instruction |
| `--image` | — | Comma-separated RGB image paths (one per view) |
| `--num-views` | `2` | Number of camera views |
| `--hardware` | `auto` | FlashRT backend (`rtx_sm89`, `rtx_sm120`, `thor`, …) |
| `--autotune` | `3` | CUDA graph autotune trials (`0` disables) |
| `--use-fp8` | on | Load weights in FP8 when supported |
| `--config` | `pi05` | FlashRT model config name |
| `--checkpoint` | *(auto)* | Override cached weight directory |
