# pi05_libero — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: compile FlashRT natives, stage into `runtime/<env-key>/`, validate, smoke `run`.

**Requires:** Linux · NVIDIA SM89 or SM120 · matching CUDA userland · FlashRT source tree · flashcli dev checkout.

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/pi05_libero"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. Build natives

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/pi05_libero/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/pi05_libero/${ENV_KEY}"
cp bundles/pi05_libero/lib/*.so "bundles/pi05_libero/${ENV_KEY}/"
```

SM89-only FA2 speedup (dev only, not for release):

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" --fa2-native-only
```

## 2. Pack (optional, for `dist/`)

```bash
bash bundles/pi05_libero/pack.sh
export BUNDLE="$(pwd)/bundles/pi05_libero/dist"
```

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. Smoke test

```bash
export HF_ENDPOINT=https://hf-mirror.com   # if needed

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg

flashcli run "$BUNDLE" \
  --image /path/to/base.jpg \
  --benchmark 5
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/pi05_libero:1.0.4` (bump version as needed).

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `NativeEnvironmentNotSupportedError` | Rebuild for this host's env key; run `flashcli models envs "$BUNDLE"` |
| `no kernel image...` | Wrong GPU/CUDA cell vs manifest `runtime` keys |
| `'GemmRunner'... fp8_nt_dev` | Rebuild FlashRT or use `_pi05_compat.py` shim |
| Weight download fails | `HF_ENDPOINT` or `--checkpoint` with pre-downloaded weights |
