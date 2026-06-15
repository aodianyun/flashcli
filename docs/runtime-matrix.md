# Runtime release matrix

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

> **Internal maintainer doc** — index from [CONTRIBUTING.md](../CONTRIBUTING.md) only; not listed in public README / `docs/README.md`.

How maintainers build **multi CUDA / SM native artifacts** and publish via **FlashHub**.

## Overview

| Bundle | SM | CUDA lines | Python ABI | Native modules |
|--------|-----|------------|------------|----------------|
| `pi05_libero` | **89**, **120** | cu124 (SM89), cu130 | **3.12** (`python_abi: 312`) | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen_nvfp4` | **120** | **cu130 only** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2` |

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

Each catalog preset has one **`bundle.repo`** in [`models.yaml`](../src/flashcli/catalog/models.yaml) (`schema_version: 7`) — a semantic FlashHub URL.

### Native `.so` naming (build time)

```text
{module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

### FlashHub publish

1. `bash scripts/release_bundle.sh --bundle <name> --clean`
2. Upload the full `dist/` tree to FlashHub
3. Update `bundle.repo` version URL in `models.yaml`

Example (see [`models.yaml`](../src/flashcli/catalog/models.yaml)):

```text
https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.3
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

Host keys: `sm89-cu124-linux-x86_64-py312`, `sm89-cu130-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`. Check: `flashcli models envs pi05_libero`.

Upload `dist/` to FlashHub; update `pi05_libero.bundle.repo`.

---

## qwen_nvfp4 (SM120 × cu130)

One FlashHub repo for two presets (`qwen3-8b-nvfp4`, `qwen36-27b-nvfp4`); weights differ via `bundle_variant`.

Update **both** presets’ `bundle.repo` (same repo URL).

Host key example: `sm120-cu130-linux-x86_64-py312`.

---

## Runtime selection (end users)

| Stage | Behavior |
|-------|----------|
| `flashcli bundle sync` | FlashHub API → manifest → preflight → source tree + this env’s `runtime/` |
| `flashcli run` | bundle venv installs torch → load `runtime/<env-key>/*.so` → weights → `entry` |

Do not use a system Python that mismatches manifest `python_abi`.

## Local debug (no FlashHub)

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

Catalog and bundle format: [model_bundle_standard.md](model_bundle_standard.md).

Local dev trees need `.so` under the manifest’s `runtime/<env-key>/` (`build.sh` → `lib/`, then stage to `runtime/`; see bundle QUICKSTART).
