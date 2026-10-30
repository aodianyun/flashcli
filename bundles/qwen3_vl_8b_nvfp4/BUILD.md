# qwen3_vl_8b_nvfp4 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: build FlashRT py312 natives, pack the v4 bundle, validate, and smoke `run` / `serve`.

**Requires:** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT source with Qwen3-VL kernels · flashcli dev checkout.

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/qwen3_vl_8b_nvfp4"
```

## 1. Build

```bash
bash bundles/qwen3_vl_8b_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

Requires `flash_rt_qwen3_vl_kernels*.so` in the selected runtime cell.

## 2. Pack

```bash
bash bundles/qwen3_vl_8b_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/qwen3_vl_8b_nvfp4/dist"
```

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. Smoke test

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --image /path/to/scene.jpg --prompt "Describe this image." --max-pixels 100000 --max-seq 1024 --max-q-seq 256
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000 --max-pixels 100000 --max-seq 1024
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/qwen3_vl_8b_nvfp4:1.0.0` (bump as needed).

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `flash_rt_qwen3_vl_kernels` missing | rebuild with `-DFLASHRT_BUILD_QWEN3_VL=ON` |
| BF16 checkpoint errors | use the FlashRT NVFP4 checkpoint |
| OOM on 16 GB | lower `--max-pixels` / `--max-seq` |
| `Qwen3VLProcessor` missing | bundle needs `transformers>=4.57.0` |
