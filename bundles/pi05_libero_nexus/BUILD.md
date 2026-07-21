# Build & Release — pi05_libero_nexus

Maintainer documentation for building and releasing the bundle.

## Prerequisites (build host)

- Linux x86_64, **Blackwell GPU** (compute capability 12.0 / `sm_120`)
- CUDA Toolkit 13.0 (`nvcc` on PATH)
- cmake ≥ 3.24, gcc ≥ 11
- python3.10 (CPython 3.10 — must match `python_abi: "310"`)
- git, rsync (or tar as fallback)
- CUTLASS v4.4.2 (auto-cloned by the build script if missing)

## Source repos

- **FlashRT** source: must contain `CMakeLists.txt` + `flash_rt/` + `cpp/` + `exec/` + `runtime/`
- **FlashRT-Nexus** source: must contain `CMakeLists.txt` + `core/` + `serve/`

## Build commands

```sh
cd /app/flashcli

# Local dev build (uses already-cloned repos). -j 4 is a good balance on a
# 32 GB RAM host: FA2 templates are memory-heavy, higher -j risks OOM.
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    -j 4

# Pack-only (skip cmake, stage existing .so — useful after manual rebuild)
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    --pack-only

# Override defaults
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    -j 4 \
    --sm 120 --cuda-tag 130 --python-minor 310 \
    --build-dir /app/FlashRT/build \
    --cpp-build-dir /tmp/flashrt-cpp \
    --nexus-build-dir /tmp/nexus-build \
    --runtime-version 1.0.0 --nexus-version 1.0.0
```

## What `_bundle_build.sh` does

1. Detects SM / CUDA / Python / OS / arch from the build host
2. **FlashRT root cmake** (`/app/FlashRT`): builds `flash_rt_kernels` + `flash_rt_fa2` pybind extensions
3. **FlashRT cpp/ standalone cmake** (`/app/FlashRT/cpp`): builds `libflashrt_exec.so` + `libflashrt_runtime.so` + `libflashrt_cpp_pi05_c.so`
4. **Nexus cmake** (`/app/FlashRT-Nexus`): builds `libcapsule_nexus_flashrt.so` (links libflashrt_exec)
5. Stages 2 Python extensions to `runtime/<env_key>/*.so`
6. Stages 3 C libs to `runtime/<env_key>/substrate/*.so` (subdir, validator skips)
7. Vendors Nexus `serve/` Python pkg to `substrate/nexus_python/` (imports rewritten `serve.*` → `nexus_python.*`)
8. Stages slim `flash_rt/` Python pkg at bundle root (Pi0.5 subset only)
9. Writes `substrate/VERSION` (single source of truth for ABI fingerprint)
10. Runs `ldd` cross-check: Nexus lib MUST link bundled exec
11. Writes `.build/manifest-overlay.json` (with `nexus_tag`, `features.nexus`)

## Validation

```sh
flashcli bundle validate bundles/pi05_libero_nexus
```

Checks:
- `flashcli-bundle.json` schema (format_version 3, protocol_version 1)
- `entry.run` / `entry.serve` module files exist
- `python_abi: "310"` matches runtime cell suffix
- `runtime/<env_key>/*.so` recognized as pybind extensions (env_key consistency)
- `flash_rt/` dir at bundle root
- (substrate validation is done by `_substrate_loader` at runtime, not by `validate`)

## Smoke test

```sh
# Validate
flashcli bundle validate bundles/pi05_libero_nexus

# Pull weights (~1.6 GB) + PaliGemma tokenizer + install deps into bundle venv
flashcli pull bundles/pi05_libero_nexus

# Run single inference (uses placeholder zeros if --image not given)
flashcli run bundles/pi05_libero_nexus \
    --prompt "pick up the red block" \
    --benchmark 5 --warmup 2

# Serve
flashcli serve bundles/pi05_libero_nexus --port 8080 &

curl http://127.0.0.1:8080/v1/substrate
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"pick up the red block"}]}'

curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=t0'
curl http://127.0.0.1:8080/v1/session/state
curl -X POST http://127.0.0.1:8080/v1/session/reset/t0
```

## Pack and release

```sh
# Pack into a distributable zip under dist/
bash bundles/pi05_libero_nexus/pack.sh

# Validate the packed bundle
flashcli bundle validate dist/pi05_libero_nexus-*/

# One-command FlashHub release (uses release-matrix.env)
bash bundles/pi05_libero_nexus/release.sh
```

## Naming conventions

| Artifact | Pattern | Example |
|---|---|---|
| Python ext | `flash_rt_*-<fr_abi>-<env_key>.so` | `flash_rt_kernels-d0db114-sm120-cu130-linux-x86_64-py310.so` |
| FlashRT C lib | `libflashrt_*-<fr_abi>-sm{SM}-cu{CU}-{os}-{arch}.so` | `libflashrt_exec-d0db114-sm120-cu130-linux-x86_64.so` |
| Nexus C lib | `libcapsule_nexus_flashrt-fr<fr>.nx<nx>-sm{SM}-cu{CU}-{os}-{arch}.so` | `libcapsule_nexus_flashrt-frd0db114.nx8f13a3a-sm120-cu130-linux-x86_64.so` |

C libs **do not** carry `-pyNNN` — they are pure C and do not depend on Python ABI. They live in the `substrate/` subdir of the runtime cell, which the existing flashcli validator skips (top-level glob only).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unrecognized native artifact filename` from `flashcli bundle validate` | A C lib `.so` was placed at top-level of `runtime/<env>/` instead of `substrate/` | Move it under `substrate/` |
| `libcapsule_nexus_flashrt does not link libflashrt_exec` at serve startup | `libflashrt_exec.so` was replaced with a different version after build | Rebuild via `build.sh` |
| `ImportError: flash_rt_kernels` during `flashcli run` | Wrong Python invoked (host py311 instead of bundle py310) | Let flashcli re-exec into bundle venv; do not bypass |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled into this build` | FlashRT root CMake was configured without `FA2_HDIMS="64;96;128;256"` (Pi0.5 SigLIP/decoder needs 256) | `cmake -B /app/FlashRT/build -DFA2_HDIMS="64;96;128;256" -DFA2_DTYPES="fp16;bf16" -DGPU_ARCH=120 && cmake --build /app/FlashRT/build -j 4 --target flash_rt_fa2`, then rerun `build.sh` |
| nvcc OOM-killed (`cicc died due to signal 15`) | Build host RAM < 32 GB or `-j` too high | Drop to `-j 2` or `-j 1`; FA2 templates are heavy |
