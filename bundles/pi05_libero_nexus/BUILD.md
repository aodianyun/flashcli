# pi05_libero_nexus — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

Maintainer workflow: compile FlashRT + FlashRT-Nexus **native** libraries, stage into `runtime/<env-key>/substrate/`, validate, smoke `run` / `serve`, pack, publish. **No Python is used at inference** — the bundle drives the FlashRT pi05 model-runtime ABI through the Nexus embedded session.

**Requires:** Linux · NVIDIA **SM120** · CUDA **13** userland · cmake ≥ 3.24 · gcc ≥ 11 · CUTLASS (auto-cloned) · FlashRT source · FlashRT-Nexus source · flashcli dev checkout.

```bash
cd /path/to/flashcli
# Host: install the Go binary (release or source)
./install.sh --from-source          # or: curl -fsSL <repo>/install.sh | sh
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_REPO=/path/to/FlashRT-Nexus
```

The manifest keeps `python_abi: "310"` only as the runtime **cell label** (`runtime/...-py310/`); no Python interpreter or venv is created. Do **not** modify FlashRT / Nexus trees — stage copies only; keep the three `.so` files from the **same** FlashRT/FlashRT-Nexus build.

## 1. Build

`build.sh` compiles the Python-free FA2 C library (`flashrt_fa2_raw`), the FlashRT C libs (`libflashrt_exec`, `libflashrt_cpp_pi05_c`, native_v2), and the Nexus host (`libcapsule_nexus_flashrt`), then stages them into `runtime/<env-key>/substrate/` and writes `substrate/VERSION`. No pybind extensions or vendored Python are produced.

```bash
# parallel jobs (FA2 templates are memory-heavy; keep some cores free)
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  -j 7
```

Pack-only (skip cmake, re-stage existing artifacts):

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  --pack-only
```

Outputs: `runtime/sm120-cu130-linux-x86_64-py310/substrate/{libflashrt_exec-*,libflashrt_cpp_pi05_c-*,libcapsule_nexus_flashrt-*,libflashrt_fa2_raw-*,VERSION}` · `.build/manifest-overlay.json`

Native-only cell (no `-py`): `runtime/sm120-cu130-linux-x86_64/substrate/*`. The build also compiles the **native-exec server** (bundle-owned, self-contained `native_exec/`) to `runtime/<env>/bin/pi05_exec_server` and copies `exec_server.json`, exposing the same model via `@exec`. The server embeds the release version (from `pyproject.toml`) — `pi05_exec_server --version` — and reports it in its readiness payload.

Optional overrides: `--sm` · `--cuda-tag` · `--python-minor` · `--build-dir` · `--cpp-build-dir` · `--nexus-build-dir` · `--runtime-version` · `--nexus-version`.

## 1b. FP8 calibration (performance)

The bundle runs PI0.5 in native **FP8** (`precision: "fp8_e4m3fn"` on SM120), ≈2× faster than BF16. The runtime does **not** calibrate implicitly: it validates a static FP8 artifact whose path is `calibration_path` in the native config (`{runtime_dir}/calib/pi05_sm120_fp8.calib`). Without it the runtime falls back to BF16.

Regenerate the artifact from **real LIBERO frames** (recommended) with:

```bash
FLASHRT_REPO=/path/to/FlashRT \
bash bundles/pi05_libero_nexus/calibrate_fp8.sh \
  --checkpoint /path/to/pi05_libero_finetuned_v044
```

`calibrate_fp8.sh` downloads a small `lerobot/libero` slice, extracts 2-view observations (frames + state + prompt) via `native_calib/extract_libero_obs.py`, compiles `native_calib/pi05_calib.cpp` against the staged substrate, and writes `calib/pi05_sm120_fp8.calib`. `build.sh` stages `calib/` into `runtime/<env>/calib/`; `pack.sh` carries it into `dist/`.

The artifact identity binds the checkpoint + tokenizer + shape (`num_views`, `chunk`, `state_dim`, `num_steps`, `max_prompt_tokens`, `stage_plan`) — regenerate it if any of those change. Requires pyarrow + ffmpeg.

## 2. Pack

```bash
bash bundles/pi05_libero_nexus/pack.sh
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus/dist"
```

Pack tree follows `release-matrix.env` `RELEASE_PACK_FILES` (manifest, engines, helpers, `flash_rt/`, runtime cell including `substrate/`).

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
flashcli models show "$BUNDLE"
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

Upload `dist/` to FlashHub as `flashcli-bundle/pi05_libero_nexus:<version>@abi` / `@exec` (bump as needed).

```bash
bash bundles/pi05_libero_nexus/release.sh
# or matrix:
bash scripts/release_bundle.sh --bundle pi05_libero_nexus --clean
```

`release-matrix.env` pins SM120 / cu130 / py310.

## Notes

- **Substrate layout:** the three C libs live under `runtime/<env_key>/substrate/`; the Go host loads them through the Nexus embedded session (`flashrt_loaded_model_open` + `nexus_embedded_*`). There is no `_substrate_loader` / Python at runtime.
- **ABI fingerprint:** `substrate/VERSION` records FlashRT + Nexus commits; Nexus `.so` should `ldd`-link the bundled `libflashrt_exec.so` (kept loadable via the manifest `preload`).
- **FA2:** Pi0.5 encoder/decoder use head_dim `256`; the default full FA2 matrix covers it. Slim to `-DFA2_HDIMS=256 -DFA2_DTYPES=bf16` only after confirming no other path needs the rest.
- **vs `pi05_libero`:** production stateful serve path; keep the smoke-oriented script bundle separate.

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `NativeEnvironmentNotSupportedError` | Rebuild for this host's env key; `flashcli models show "$BUNDLE"` |
| `unrecognized native artifact filename` | Move C libs under `substrate/`, not runtime cell top-level |
| `libcapsule_nexus_flashrt does not link libflashrt_exec` | Rebuild with `build.sh` (do not swap one lib alone) |
| `no file matches {runtime_dir}/substrate/...` | Ensure the three `.so` are staged and the manifest `library`/`session_library`/`preload` globs each match exactly one file |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled` | Reconfigure FlashRT with `-DFA2_HDIMS="64;96;128;256"` then rebuild FA2 + `build.sh` |
| nvcc OOM (`cicc died due to signal 15`) | Drop to `-j 2` or `-j 1` |
| Weight download fails | Check ModelScope access; or `--checkpoint` with a local dir |
