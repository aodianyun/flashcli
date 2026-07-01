# groot_n16

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

GROOT N1.6 VLA; weights [nvidia/GR00T-N1.6-3B](https://huggingface.co/nvidia/GR00T-N1.6-3B).

**GPU**: NVIDIA **SM120** (Blackwell) · CUDA **13.x** · Python **3.12**

## Files required to run inference (after sync)

```text
flashcli-bundle.json
run.py
_groot_infer.py
_groot_compat.py
flash_rt/
runtime/sm120-cu130-linux-x86_64-py312/   # *.so for this host
```

Weights are downloaded by flashcli to `~/.flashcli/models/groot_n16/.../checkpoint/`, not shipped in the bundle.

## Entry

`flashcli-bundle.json` uses **script mode**: `run.main(argv)`; does **not** `import flashcli_bundle`. Checkpoint path comes from `FLASHCLI_CHECKPOINT` (set by `flashcli run`).

Default embodiment: **`gr1`** (1 camera view). Other trained tags in the base checkpoint: `robocasa_panda_omron` (3 views), `behavior_r1_pro` (3 views).

## End users

See **[QUICKSTART.md](QUICKSTART.md)** for build, pack, and run commands.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| HuggingFace download fails | Set `HF_ENDPOINT=https://hf-mirror.com` or pre-download and `--checkpoint` |
| Output looks like noise | Use a trained `embodiment_tag` (`gr1`, `robocasa_panda_omron`, `behavior_r1_pro`) |
| `num_views` mismatch | `gr1` → 1 view; `robocasa_panda_omron` / `behavior_r1_pro` → 3 views |
| Tokenizer load fails | Ensure checkpoint includes `tokenizer/`, or pre-download `Qwen/Qwen3-1.7B` tokenizer |
| `'GemmRunner'... fp8_nt_dev` | Rebuild FlashRT, or `_groot_compat.py` shims older `.so` builds |
