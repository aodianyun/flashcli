# qwen3_8b_nvfp4 — build & smoke test

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：编译 py312 FlashRT native、打包 v4 bundle、校验并冒烟 `run` / `serve`。

**要求：** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/qwen3_8b_nvfp4"
```

## 1. 编译

```bash
bash bundles/qwen3_8b_nvfp4/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --python-bin /usr/bin/python3.12 \
  --python-minor 312 \
  -j "$(nproc)"
```

产物： `runtime/sm120-cu130-linux-x86_64-py312/*.so`, `flash_rt/`, `.build/manifest-overlay.json`.

## 2. 打包

```bash
bash bundles/qwen3_8b_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/qwen3_8b_nvfp4/dist"
```

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. 冒烟测试

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --prompt "Hello" --max-tokens 128
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 为 `flashcli-bundle/qwen3_8b_nvfp4:1.0.0`（按实际版本号调整）.

## 故障排查（构建）

| Symptom | Fix |
|---------|-----|
| Missing Python3 development components | use `--python-bin /usr/bin/python3.12` and a fresh `--build-dir` |
| `NativeEnvironmentNotSupportedError` | rebuild with the matching SM/CUDA cell |
| Weight download fails | set `HF_ENDPOINT` or use `flashcli pull` |
