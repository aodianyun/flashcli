# GROOT N1.6

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**NVIDIA GR00T N1.6** is a vision–language–action (VLA) foundation model for generalist robot policies. This preset runs the **3B** checkpoint [`nvidia/GR00T-N1.6-3B`](https://huggingface.co/nvidia/GR00T-N1.6-3B) on **FlashRT**, turning a natural-language task and camera images into multi-step robot actions.

| | |
|---|---|
| **Ref** | `flashcli-bundle/groot_n16:1.0.0` |
| **Weights** | [nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.12** (bundle venv) |
| **Capabilities** | `run` |

**Inputs:** task prompt + one or more RGB images.  
**Output:** action sequence (joint / end-effector commands per embodiment).

**Embodiment tags** trained in the base checkpoint:

| Tag | Views | Robot setup |
|-----|-------|-------------|
| `gr1` *(default)* | 1 | Humanoid GR-1 |
| `robocasa_panda_omron` | 3 | RoboCasa + Panda |
| `behavior_r1_pro` | 3 | BEHAVIOR R1 Pro |

`--num-views` must match the tag. A wrong tag or view count often produces meaningless actions.

Weights and a Qwen3 tokenizer are pulled automatically on first run (not included in the bundle zip).

## Run

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg
```

Smoke test without images (placeholder frames):

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --embodiment-tag gr1 \
  --num-views 1
```

Three-camera embodiment:

```bash
flashcli run flashcli-bundle/groot_n16:1.0.0 \
  --prompt "open the drawer" \
  --embodiment-tag robocasa_panda_omron \
  --num-views 3 \
  --image /path/v0.jpg,/path/v1.jpg,/path/v2.jpg
```

Full flags: `flashcli run flashcli-bundle/groot_n16:1.0.0 --help`

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `pick up the cup on the table` | Task instruction |
| `--image` | — | Comma-separated RGB paths (one per view) |
| `--embodiment-tag` | `gr1` | Policy slot (`gr1`, `robocasa_panda_omron`, `behavior_r1_pro`) |
| `--num-views` | `1` | Must match embodiment |
| `--action-horizon` | `16` | Action steps (`50` for full horizon) |
| `--hardware` | `auto` | FlashRT backend |
| `--autotune` | `3` | CUDA graph autotune trials |
| `--use-fp8` | on | FP8 weights when supported |
| `--use-fp16` | off | Full FP16 baseline |
| `--config` | `groot` | FlashRT config name |
