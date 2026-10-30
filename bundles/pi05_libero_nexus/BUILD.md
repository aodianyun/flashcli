# pi05_libero_nexus — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: build the FlashRT-Nexus native substrates, pack the v4 native-abi bundle, validate, and smoke `run` / `serve`.

**Requires:** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT source · FlashRT-Nexus source · flashcli dev checkout.

```bash
cd /path/to/flashcli
./install.sh --from-source
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_SRC=/path/to/FlashRT-Nexus
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
```

## 1. Build

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_SRC" \
  -j "$(nproc)"
```

Outputs: `runtime/sm120-cu130-linux-x86_64/{substrate,bin,calib}/`, `.build/manifest-overlay.json`.

## 2. Pack

```bash
bash bundles/pi05_libero_nexus/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus/dist"
```

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
flashcli models show "$BUNDLE"
```

## 4. Smoke test

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --prompt "pick up the red block and place it in the tray" --image /path/v0.jpg,/path/v1.jpg
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8080
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/pi05_libero_nexus:1.0.3` (bump as needed). The exec example is not packed or published.

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| Missing Nexus source | pass `--nexus-src` or set `NEXUS_SRC` |
| `NativeEnvironmentNotSupportedError` | rebuild the SM120/cu130 native-abi cell |
| Weight download fails | set `HF_ENDPOINT` or use `flashcli pull` |
