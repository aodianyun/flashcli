# qwen3_8b_nvfp4 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: build the FlashRT py312 natives, pack the v4 bundle, validate, and smoke `run` / `serve`.

**Requires:** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT source tree · flashcli dev checkout.

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/qwen3_8b_nvfp4"
```

## 1. Build

```bash
bash bundles/qwen3_8b_nvfp4/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --python-bin /usr/bin/python3.12 \
  --python-minor 312 \
  -j "$(nproc)"
```

Outputs: `runtime/sm120-cu130-linux-x86_64-py312/*.so`, `flash_rt/`, `.build/manifest-overlay.json`.

## 2. Pack

```bash
bash bundles/qwen3_8b_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/qwen3_8b_nvfp4/dist"
```

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. Smoke test

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --prompt "Hello" --max-tokens 128
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/qwen3_8b_nvfp4:1.0.0` (bump as needed).

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| Missing Python3 development components | use `--python-bin /usr/bin/python3.12` and a fresh `--build-dir` |
| `NativeEnvironmentNotSupportedError` | rebuild with the matching SM/CUDA cell |
| Weight download fails | set `HF_ENDPOINT` or use `flashcli pull` |
