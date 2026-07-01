# Runtime release matrix

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

> **Internal maintainer doc** — index from [CONTRIBUTING.md](../CONTRIBUTING.md) only; not listed in public README / `docs/README.md`.

How maintainers build **multi CUDA / SM native artifacts** and publish via **FlashHub**.

## Overview

| Bundle | SM | CUDA lines | Python ABI | Native modules |
|--------|-----|------------|------------|----------------|
| `pi05_libero` | **89**, **120** | cu124 (SM89), cu130 | **3.12** (`python_abi: 312`) | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2`, `flash_rt_fp4` |
| `qwen3_vl_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2`, `flash_rt_fp4`, `flash_rt_qwen3_vl_kernels` |
| `groot_n16` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2` *(local dev; not on FlashHub yet)* |

OS / arch: **linux-x86_64**. Config: `bundles/<name>/release-matrix.env`.

## Publish layout (`dist/`)

After `pack_bundle.sh`:

```text
dist/
  flashcli-bundle.json    # runtime: { env_key: "runtime/<env-key>" }
  run.py, flash_rt/, ...
  runtime/
    sm89-cu124-linux-x86_64-py312/
      flash_rt_kernels-...-py312.so
      flash_rt_fa2-...-py312.so
    ...
```

At runtime, flashcli loads matching `.so` files directly from `runtime/<env-key>/` in the cached bundle root (no copy to `lib/`).

Each published bundle is pinned by a **FlashHub ref** (`flashcli-bundle/<name>:<version>[@variant]`) — see [model_bundle_standard.md](model_bundle_standard.md).

### Native `.so` naming (build time)

```text
{module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

### FlashHub publish

1. `bash scripts/release_bundle.sh --bundle <name> --clean`
2. Upload the full `dist/` tree to FlashHub
3. Tell users to pin the new ref (e.g. bump version in `flashcli-bundle/pi05_libero:1.0.4`)

Example repo URL:

```text
https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.4
```

## Shared release pipeline

| Script | Role |
|--------|------|
| [`scripts/release_bundle.sh`](../scripts/release_bundle.sh) | **Recommended**: FlashRT → matrix build → finalize → pack |
| [`scripts/build_release_matrix.sh`](../scripts/build_release_matrix.sh) | Host matrix loop |
| [`scripts/pack_bundle.sh`](../scripts/pack_bundle.sh) | Write `runtime/` dirs + update manifest |

**One command:**

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

**Local single-env dev:**

```bash
cd bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
```

---

## pi05_libero

**GPU**: SM89 (Ada) and SM120 (Blackwell). **CUDA**: cu124 (SM89 only); cu130 (SM89 + SM120 — cu130 matrix pass also cross-builds `sm120-cu130`).

Host keys: `sm89-cu124-linux-x86_64-py312`, `sm89-cu130-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`. Check: `flashcli models envs flashcli-bundle/pi05_libero:1.0.4`.

Upload `dist/` to FlashHub; users pin `flashcli-bundle/pi05_libero:<version>`.

---

## qwen_nvfp4 (SM120 × cu130)

One FlashHub repo (`flashcli-bundle/qwen_nvfp4:1.0.1`); weights differ via `@qwen3` / `@qwen36` in the ref.

Document both variant refs (`@qwen3`, `@qwen36`) for the same repo URL.

Host key example: `sm120-cu130-linux-x86_64-py312` (NVIDIA). Env keys use a fixed tail `-{os}-{arch}-py{PY}` with an opaque `platform_tail` prefix; non-NVIDIA cells (e.g. `gfx942-rocm611-linux-x86_64-py312`) are matched from manifest `runtime` the same way. Host auto-detection still emits NVIDIA-style keys; set `FLASHCLI_RUNTIME_ENV_KEY` to force a manifest cell when testing new platforms.

---

## Runtime selection (end users)

| Stage | Behavior |
|-------|----------|
| `flashcli bundle sync` | FlashHub API → manifest → preflight → source tree + this env’s `runtime/` |
| `flashcli run` | bundle venv installs torch → load `runtime/<env-key>/*.so` → weights → `entry` |

Do not use a system Python that mismatches manifest `python_abi`.

## Local debug (no FlashHub)

```bash
flashcli run bundles/pi05_libero \
  --image /path/to.jpg
```

Preset ref and bundle format: [model_bundle_standard.md](model_bundle_standard.md).

Local dev trees need `.so` under the manifest’s `runtime/<env-key>/` (`build.sh` → `lib/`, then stage to `runtime/`; see bundle QUICKSTART).
