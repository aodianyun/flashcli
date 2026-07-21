# pi05_libero_nexus — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: compile FlashRT + FlashRT-Nexus natives, stage into `runtime/<env-key>/` (+ `substrate/`), validate, smoke `run` / `serve`, pack, publish.

**Requires:** Linux · NVIDIA **SM120** · CUDA **13** userland · cmake ≥ 3.24 · gcc ≥ 11 · **Python 3.10** · FlashRT source · FlashRT-Nexus source · flashcli dev checkout.

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_REPO=/path/to/FlashRT-Nexus
```

This bundle uses **Python 3.10** (`python_abi: "310"`). Native `.so` files must match py310. Do **not** modify FlashRT / Nexus trees — stage copies only; keep `flash_rt/` and `.so` from the **same** FlashRT commit.

## 1. Build

`build.sh` builds FlashRT pybind + C libs + Nexus capsule, stages tagged `.so`, vendors slim `flash_rt/` and `substrate/nexus_python/`, writes `substrate/VERSION`.

```bash
# -j 4 is a good balance on 32 GB RAM (FA2 templates are memory-heavy)
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  -j 4
```

Pack-only (skip cmake, re-stage existing artifacts):

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  --pack-only
```

Outputs: `flash_rt/` · `runtime/sm120-cu130-linux-x86_64-py310/*.so` · `runtime/.../substrate/{*.so,nexus_python/,VERSION}` · `.build/manifest-overlay.json`

Optional overrides: `--sm` · `--cuda-tag` · `--python-minor` · `--build-dir` · `--cpp-build-dir` · `--nexus-build-dir` · `--runtime-version` · `--nexus-version`.

## 2. Pack

```bash
bash bundles/pi05_libero_nexus/pack.sh
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus/dist"
```

Pack tree follows `release-matrix.env` `RELEASE_PACK_FILES` (manifest, engines, helpers, `flash_rt/`, runtime cell including `substrate/`).

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. Smoke test

Weights from ModelScope (`lerobot/pi05_libero_finetuned_v044`, ~7 GB) + PaliGemma tokenizer via `post_pull`. After `pull`, inference stays offline.

```bash
export HF_ENDPOINT=https://hf-mirror.com   # optional (CN)

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg

flashcli run "$BUNDLE" --benchmark 5 --warmup 2

flashcli serve "$BUNDLE" --port 8080 &
curl http://127.0.0.1:8080/v1/substrate
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"x"}],
       "extras":{"images":[]}}'
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=t0'
curl -X POST http://127.0.0.1:8080/v1/session/reset/t0
```

Also validate the packed tree: `flashcli bundle validate dist/pi05_libero_nexus-*/` (path as produced by `pack.sh`).

## 5. Publish

Upload `dist/` to FlashHub as `flashcli-bundle/pi05_libero_nexus:1.0.0` (bump as needed).

```bash
bash bundles/pi05_libero_nexus/release.sh
# or matrix:
bash scripts/release_bundle.sh --bundle pi05_libero_nexus --clean
```

`release-matrix.env` pins SM120 / cu130 / py310.

## Notes

- **Substrate layout:** C libs live under `runtime/<env_key>/substrate/` (validator top-level `*.so` glob skips them; `_substrate_loader` loads + ABI-checks at runtime).
- **ABI fingerprint:** `substrate/VERSION` records FlashRT + Nexus commits; Nexus `.so` must `ldd`-link the bundled `libflashrt_exec.so`.
- **FA2:** Pi0.5 needs `FA2_HDIMS` including `256` (SigLIP / decoder).
- **vs `pi05_libero`:** production stateful serve path; keep the smoke-oriented script bundle separate.

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `NativeEnvironmentNotSupportedError` | Rebuild for this host's env key; `flashcli models envs "$BUNDLE"` |
| `unrecognized native artifact filename` | Move C libs under `substrate/`, not runtime cell top-level |
| `libcapsule_nexus_flashrt does not link libflashrt_exec` | Rebuild with `build.sh` (do not swap one lib alone) |
| `ImportError: flash_rt_kernels` | Use flashcli re-exec into bundle py310 venv; do not bypass |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled` | Reconfigure FlashRT with `-DFA2_HDIMS="64;96;128;256"` then rebuild FA2 + `build.sh` |
| nvcc OOM (`cicc died due to signal 15`) | Drop to `-j 2` or `-j 1` |
| Weight download fails | Check ModelScope access; or `--checkpoint` with a local dir |
