# GROOT N1.7

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**NVIDIA GR00T N1.7** is a vision–language–action (VLA) foundation model for generalist robot policies. This preset runs the **3B** checkpoint [`nvidia/GR00T-N1.7-3B`](https://huggingface.co/nvidia/GR00T-N1.7-3B) on **FlashRT** using the N1.7 contract: preprocess images and prompt with vendored **Isaac-GR00T** `Gr00tPolicy` (bundled under `gr00t/`, no pip install) to build `aux`, then `set_prompt` + `infer` on FlashRT.

| | |
|---|---|
| **Ref** | `flashcli-bundle/groot_n17:1.0.0` |
| **Weights** | [nvidia/GR00T-N1.7-3B](https://huggingface.co/nvidia/GR00T-N1.7-3B) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.10** (bundle venv; Isaac-GR00T official) |
| **Capabilities** | `run` |

**Inputs:** task prompt + one or more RGB images (optional zero-state; optional `--state` npz).  
**Output:** denormalized action dict per embodiment modality (e.g. `eef_9d`, `joint_position`).

**Common embodiment tags** (see `flash_rt/models/groot_n17/embodiments.py` for the full list):

| Tag | Views | Notes |
|-----|-------|-------|
| `oxe_droid_relative_eef_relative_joint` *(default)* | 2 | OXE Droid relative EEF + joints |
| `gr1_unified` | 2 | Humanoid GR-1 unified |
| `libero_sim` | 2 | LIBERO simulation |
| `simpler_env_google` | 1 | SimplerEnv Google robot |

`--num-views` must match the tag. Real images are recommended; placeholder frames are only for smoke tests.

Weights are pulled automatically on first run (checkpoint is self-contained; no extra tokenizer sidecar).

## Run

```bash
flashcli run flashcli-bundle/groot_n17:1.0.0 \
  --prompt "put the blue block in the green bowl" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --image /path/v0.jpg,/path/v1.jpg
```

Smoke test without images (placeholder frames + zero state):

```bash
flashcli run flashcli-bundle/groot_n17:1.0.0 \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2
```

Full flags: `flashcli run flashcli-bundle/groot_n17:1.0.0 --help`

## Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `put the blue block in the green bowl` | Task instruction |
| `--image` | — | Comma-separated RGB paths (one per view) |
| `--state` | — | Optional `.npz` with `state.*` arrays for normalization / relative-action decode |
| `--embodiment-tag` | `oxe_droid_relative_eef_relative_joint` | Policy slot |
| `--num-views` | `2` | Must match embodiment |
| `--action-horizon` | `40` | Action steps |
| `--hardware` | `auto` | FlashRT backend |
| `--autotune` | `3` | CUDA graph autotune trials |
| `--use-fp8` | on | FP8 weights when supported |
| `--use-fp16` | off | Full FP16 baseline |
| `--config` | `groot_n17` | FlashRT config name |
| `--seed` | `0` | RNG seed for Gr00tPolicy aux capture |
