# wan22 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: stage FlashRT Python + Wan package + tagged `.so`, pack, validate, smoke `run`, publish.

**Requires:** Linux · NVIDIA SM120 · CUDA 13 userland · FlashRT source (with buildable `.so`) · Wan2.2 official checkout (`wan/` package) · flashcli dev install.

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/wan22"
export FLASHRT_REPO=/path/to/FlashRT
export WAN_ROOT=/path/to/Wan2.2
```

This bundle uses **Python 3.10** (`python_abi: "310"`). Native `.so` files must match py310.

## 1. Build

`build.sh` stages a minimal `flash_rt/` (version-locked to the `.so`), vendors the Wan `wan/` package (t2v subset), and copies tagged kernels under `runtime/<env-key>/`.

```bash
bash bundles/wan22/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --wan-root "$WAN_ROOT"
```

Options: `--env-key`, `--flashrt-abi`, `--python-minor`. SM/CUDA are auto-detected from `nvidia-smi` / `nvcc`. When gcc-11 is present it is forced as the nvcc host compiler (glibc 2.35–compatible `.so`).

Outputs: `flash_rt/`, `wan/`, `runtime/sm120-cu130-linux-x86_64-py310/*.so`, `flash_rt/BUNDLE_VERSION`

## 2. Pack

```bash
bash bundles/wan22/pack.sh
export BUNDLE="$(pwd)/bundles/wan22/dist"
```

`pack.sh` → `scripts/pack_bundle.sh`. Upload tree includes `flashcli-bundle.json`, `run.py`, `flash_rt/`, `wan/`, and `runtime/<env-key>/` (`RELEASE_PACK_FILES` in `release-matrix.env`).

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. Smoke test

Weights come from ModelScope (`Wan-AI/Wan2.2-TI2V-5B`, ~34 GB). Inference always runs with `HF_HUB_OFFLINE=1` after pull.

```bash
flashcli pull "$BUNDLE"

# Fastest end-to-end check (~20–40s on a free GPU once deps are cached):
PYTHONUNBUFFERED=1 flashcli run "$BUNDLE" \
  --frames 5 --steps 2 --out smoke.mp4

# 5060 Ti baseline (832×480, 81 frames, 20 steps):
flashcli run "$BUNDLE"

# Image-to-video:
flashcli run "$BUNDLE" \
  --mode i2v --image /path/start.png --frames 81
```

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/wan22:1.0.0` (bump version as needed).

Multi-env matrix (Docker):

```bash
bash scripts/release_bundle.sh --bundle wan22 --clean
```

`release-matrix.env` pins SM120 / cu130 / py310; `_bundle_build.sh` implements matrix-cell + finalize hooks (`scripts/lib/bundle_hooks.sh`).

## Notes

- **No FlashRT / Wan source edits**: copies are unmodified. Missing `flash_attn` is handled by a runtime rebinding of vendored Wan attention to its SDPA fallback (`run.py`).
- **Version lock**: `flash_rt/` and the `.so` are staged from one FlashRT commit per build (`flash_rt/BUNDLE_VERSION`).
- **Weights**: not in the zip; fetched by `pull` from ModelScope.

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `NativeEnvironmentNotSupportedError` | Rebuild for this host’s env key; `flashcli models envs "$BUNDLE"` |
| `no kernel image...` | Wrong GPU/CUDA cell vs manifest `runtime` keys |
| Invalid Wan root | Point `--wan-root` at a checkout that contains the `wan/` package |
| Weight download fails | Check ModelScope access; or pre-place checkpoint and use local path tooling |
| OOM on ≤16 GB | Keep `--offload-model true`; lower `--width` / `--height` / `--frames` |
| `frames` rejected | Must satisfy `4n+1` |
