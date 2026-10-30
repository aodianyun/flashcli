# Runtime release matrix

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

> **Internal maintainer doc** — index from [CONTRIBUTING.md](../CONTRIBUTING.md) only; not listed in public README / `docs/README.md`.

How maintainers build **multi CUDA / SM native artifacts** and publish via **FlashHub**.

## Overview

| Bundle | SM | CUDA lines | Python ABI | Native modules |
|--------|-----|------------|------------|----------------|
| `pi05_libero` | **89**, **120** | cu124 (SM89), cu130 | **3.12** (`python_abi: 312`) | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen3_vl_8b_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2`, `flash_rt_fp4`, `flash_rt_qwen3_vl_kernels` |
| `groot_n16` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2` |
| `higgs_audio` | **120** | **cu130 only** | **3.10** | `flash_rt_kernels`, `flash_rt_fa2` |
| `wan22` | **120** | **cu130 only** | **3.10** | `flash_rt_kernels` |
| `qwen3_8b_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2`, `flash_rt_fp4` |
| `qwen36_27b_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2`, `flash_rt_fp4` |
| `pi05_libero_nexus` | **120** | **cu130 only** | **none** | `runtime/<dir>/substrate/` C libs (native-abi) |

| `groot_n17` | **120** | **cu130 only** | **3.10** *(Isaac-GR00T)* | `flash_rt_kernels`, `flash_rt_fa2` |

OS / arch: **linux-x86_64**. Config: `bundles/<name>/release-matrix.env`.

## Publish layout (`dist/`)

After `pack_bundle.sh`:

```text
dist/
  flashcli-bundle.json    # environments: { env_key: { runtime: "runtime/<runtime-dir>" } }
  run.py, flash_rt/, ...
  runtime/
    sm89-cu124-linux-x86_64-py312/
      flash_rt_kernels-...-py312.so
      flash_rt_fa2-...-py312.so
    ...
```

At runtime, flashcli loads matching `.so` files directly from `runtime/<runtime-dir>/` in the cached bundle root (no copy to `lib/`).

Each published bundle is pinned by a **FlashHub ref** (`flashcli-bundle/<name>:<version>`) — see [model_bundle_standard.md](model_bundle_standard.md).

### Native `.so` naming (build time)

```text
{module}-{FlashRT_ABI}-{build_tag}.so
```

### FlashHub publish

1. `bash scripts/release_bundle.sh --bundle <name> --clean` (current env; add `--matrix` for full matrix)
2. Upload the full `dist/` tree to FlashHub
3. Tell users to pin the new ref (e.g. bump version in `flashcli-bundle/pi05_libero:1.0.5`)

Example repo URL:

```text
https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.5
```

## Shared release pipeline

| Script | Role |
|--------|------|
| [`scripts/release_bundle.sh`](../scripts/release_bundle.sh) | **Recommended**: current host env by default; `--matrix` for full Docker/multi-CUDA matrix |
| [`scripts/build_release_matrix.sh`](../scripts/build_release_matrix.sh) | Explicit host matrix loop |
| [`scripts/pack_bundle.sh`](../scripts/pack_bundle.sh) | Pack current env; `--all-envs` / `--verify-matrix` for full matrix |

**One command (current env):**

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

**Full matrix (opt-in):**

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --matrix --clean
```

**Local single-env dev:**

```bash
cd bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
```

---

## pi05_libero

**GPU**: SM89 (Ada) and SM120 (Blackwell). **CUDA**: cu124 (SM89 only); cu130 (SM89 + SM120 — cu130 matrix pass also cross-builds `sm120-cu130`).

Host keys: `sm89-cu124-linux-x86_64-py312`, `sm89-cu130-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`. Check: `flashcli models show flashcli-bundle/pi05_libero:1.0.5`.

Upload `dist/` to FlashHub; users pin `flashcli-bundle/pi05_libero:<version>`.

---

## Runtime selection (end users)

| Stage | Behavior |
|-------|----------|
| `flashcli bundle sync` | FlashHub API → manifest → preflight → source tree + this env’s `runtime/` |
| `flashcli run` | bundle venv installs torch → load `runtime/<runtime-dir>/*.so` → weights → `entry` |

Do not use a system Python that mismatches manifest `python_abi`.

## Local debug (no FlashHub)

```bash
flashcli run bundles/pi05_libero \
  --image /path/to.jpg
```

Preset ref and bundle format: [model_bundle_standard.md](model_bundle_standard.md).

Local dev trees need `.so` under the selected environment’s `runtime/<runtime-dir>/` (`build.sh` → `lib/`, then stage to `runtime/`; see bundle `BUILD.md`).
