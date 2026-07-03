# qwen3_vl_nvfp4 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. Build natives

```bash
bash bundles/qwen3_vl_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen3_vl_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen3_vl_nvfp4/${ENV_KEY}"
cp bundles/qwen3_vl_nvfp4/lib/*.so "bundles/qwen3_vl_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

Requires `flash_rt_qwen3_vl_kernels*.so` in the runtime cell.

## 2. Weights (maintainer)

Runtime needs **FlashRT NVFP4** checkpoint (not BF16 `Qwen/Qwen3-VL-8B-Instruct`):

```bash
bash bundles/qwen3_vl_nvfp4/scripts/prepare_qwen3_vl_weights.sh \
  --flashrt-repo "$FLASHRT_REPO" \
  --dst /tmp/Qwen3-VL-8B-FlashRT-NVFP4

# Dev embed:
bash bundles/qwen3_vl_nvfp4/build.sh --embed-checkpoint /tmp/Qwen3-VL-8B-FlashRT-NVFP4
```

After HF publish, update `weights.repo` in manifest and:

```bash
bash bundles/qwen3_vl_nvfp4/pack.sh
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4/dist"
flashcli pull "$BUNDLE"
```

## 3. Smoke test — run

```bash
flashcli run "$BUNDLE" \
  --image /path/to/scene.jpg \
  --prompt "Describe this image." \
  --max-tokens 64
```

## 4. Smoke test — serve

```bash
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000 --warmup-preset short

curl -s http://127.0.0.1:8000/health | jq
```

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `flash_rt_qwen3_vl_kernels is not built` | Rebuild with `-DFLASHRT_BUILD_QWEN3_VL=ON` (`build.sh` enables this) |
| BF16 checkpoint errors | Quantize with `prepare_qwen3_vl_weights.sh` |
| OOM on 16 GB | Lower `--max-pixels` and `--max-seq` |
| `Qwen3VLProcessor` missing | Bundle needs `transformers>=4.57.0` |
