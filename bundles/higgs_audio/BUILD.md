# higgs_audio — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: stage FlashRT py310 natives + minimal `flash_rt/`, pack, validate, and smoke `run`.

**Requires:** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT source built for Python 3.10 · flashcli dev checkout.

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/higgs_audio"
```

## 1. Build

```bash
bash bundles/higgs_audio/build.sh --repo-root "$FLASHRT_REPO"
```

Outputs: `runtime/sm120-cu130-linux-x86_64-py310/*.so`, `flash_rt/`. The build stages existing py310 artifacts; it does not compile FlashRT.

## 2. Pack

```bash
bash bundles/higgs_audio/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/higgs_audio/dist"
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
flashcli run "$BUNDLE" --text "Hello world" --out /tmp/higgs.wav
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/higgs_audio:1.0.1` (bump as needed).

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| Py310 native missing | build FlashRT with Python 3.10, then rerun `build.sh` |
| `NativeEnvironmentNotSupportedError` | rebuild the SM120/cu130/py310 cell |
| torchaudio load error | the bundle stubs unusable torchaudio; rebuild/pack with the current `env_guard.py` |
