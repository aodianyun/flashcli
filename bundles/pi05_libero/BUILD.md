# pi05_libero — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: compile FlashRT natives, stage into `runtime/<runtime-dir>/`, validate, smoke `run`.

**Requires:** Linux · NVIDIA SM89 or SM120 · matching CUDA userland · FlashRT source tree · flashcli dev checkout.

```bash
cd /path/to/flashcli
# Host: install the Go binary (release or source), then the protocol pkg for local dev
./install.sh --from-source          # or: curl -fsSL <repo>/install.sh | sh
pip install -e ./flashcli-bundle
export BUNDLE="$(pwd)/bundles/pi05_libero"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. Build natives

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
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
flashcli models show "$BUNDLE"
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

Upload `dist/` to FlashHub as `flashcli-bundle/pi05_libero:1.0.5` (bump version as needed).

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `NativeEnvironmentNotSupportedError` | Rebuild for this host's env key; run `flashcli models show "$BUNDLE"` |
| `no kernel image...` | Wrong GPU/CUDA cell vs manifest `runtime` keys |
| `'GemmRunner'... fp8_nt_dev` | Rebuild FlashRT or use `_pi05_compat.py` shim |
| Weight download fails | `HF_ENDPOINT` or `--checkpoint` with pre-downloaded weights |
