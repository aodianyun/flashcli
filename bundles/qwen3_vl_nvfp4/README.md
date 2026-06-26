# qwen3_vl_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

**Qwen3-VL-8B NVFP4** multimodal bundle — image + text `run` and OpenAI-compatible `serve` with true SSE streaming and tool calls.

## Layout

`format_version: 3` manifest with `runtime: { env_key: path }`. Native `.so` live under `runtime/<env-key>/` on FlashHub and after sync. Requires **SM120 × cu130 × Python 3.12** (bundle venv). Weights are **not** in the bundle — pull FlashRT NVFP4 checkpoint from Hugging Face (see weights note below).

| Component | Notes |
|-----------|-------|
| `flash_rt_kernels` | NVFP4 language GEMM (SM120) |
| `flash_rt_fa2` | FA2 attention |
| `flash_rt_qwen3_vl_kernels` | Vision tower + multimodal scatter |
| Bundle engine | `_engine_qwen3_vl.py` (not FlashRT examples) |

## Weights

Runtime expects a **FlashRT NVFP4** checkpoint (not raw BF16 `Qwen/Qwen3-VL-8B-Instruct`). Maintainers: run [`scripts/prepare_qwen3_vl_weights.sh`](scripts/prepare_qwen3_vl_weights.sh), upload to HF, update `flashcli-bundle.json` `weights.repo`. Dev: `--embed-checkpoint` after quantize.

## Run

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg --prompt "Describe this image." --max-tokens 128

flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --host 0.0.0.0 --port 8000 --max-pixels 500000
```

Local bundle (no FlashHub):

```bash
flashcli run bundles/qwen3_vl_nvfp4 --image scene.jpg --prompt "Describe this image."
```

## Limits (v1)

- Supports: `image` / `image_url`, streaming SSE, EOS, sampling, tools / `tool_calls`
- Not supported: thinking / `reasoning_content`, video

**16 GB VRAM tip:** `--max-pixels 500000`, `--max-seq 2048`.
