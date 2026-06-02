# Runtime release matrix

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

How maintainers build **multi-environment native matrices** (`lib/*.so`) and ship **one zip per model**. End users install a single `bundle.zip`; flashcli picks the matching artifact at runtime.

## Overview

| Bundle | SM label | CUDA lines | Python ABI | Native modules |
|--------|----------|------------|------------|----------------|
| `pi05_libero` | **89** | **cu124**, **cu130** | 3.10 / 3.11 / 3.12 | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen_nvfp4` | **120** | **cu130** only | 3.10 / 3.11 / 3.12 | `flash_rt_kernels` (NVFP4 inside), `flash_rt_fa2` |

OS / arch for all published bundles: **linux-x86_64**.

Configuration lives in `bundles/<name>/release-matrix.env`. Build logic is shared under `scripts/`; bundle-specific cmake/staging is in `bundles/<name>/_bundle_build.sh`.

## One zip, many environments (`native_layout: matrix`)

```text
{bundle}/
  flashcli-bundle.json    # native_layout: matrix, native_matrix: [...]
  lib/
    flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py310.so
    flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py310.so
    ... (other cu/py cells)
  flash_rt/
  run.py                    # (+ bundle-specific helpers)
```

At **`flashcli run`**, flashcli selects **`lib/*.so`** matching **GPU SM + CUDA userland + OS + arch + Python ABI**. No match → `NativeEnvironmentNotSupportedError`.

Each catalog preset points at **one** `bundle.zip` in [`models.yaml`](../src/flashcli/catalog/models.yaml) (`schema_version: 6`).

### Native `.so` naming

```text
{module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

Example: `flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

- **FlashRT_ABI**: sanitized `git describe --tags --always`, or shortened commit id when too long
- Import names remain `flash_rt_kernels` / `flash_rt_fa2` regardless of filename tags

### Release zip naming

```text
{ZIP_PREFIX}-{FlashRT_ABI}-sm{SM}-multi-linux-x86_64-{YYYYMMDD-HHMMSS}.zip
```

Example: `flashcli-bundle-pi05-7cf622f-sm89-multi-linux-x86_64-20260529-193354.zip`

Implemented in `scripts/pack_bundle.sh` + `scripts/lib/release_naming.sh`.

## Shared release pipeline

| Script | Role |
|--------|------|
| [`scripts/release_bundle.sh`](../scripts/release_bundle.sh) | **Recommended**: clone/update FlashRT → Docker (or `--native`) per CUDA line → finalize manifest → pack zip |
| [`scripts/build_release_matrix.sh`](../scripts/build_release_matrix.sh) | Host matrix loop; read `release-matrix.env` |
| [`scripts/pack_bundle.sh`](../scripts/pack_bundle.sh) | Matrix + ABI verify → runtime-only zip |
| [`scripts/run_bg.sh`](../scripts/run_bg.sh) | Optional: background run + local log file |
| [`scripts/lib/bundle_hook_runner.sh`](../scripts/lib/bundle_hook_runner.sh) | Invokes `_bundle_build.sh` for each matrix cell / finalize |

Each matrix cell: **fresh build dir + full cmake** for one `(cuda × python)` pair. Cells merge into flat `lib/` via `--merge-native`.

### Python ABI verification (compile-time, required)

After all matrix cells finish, [`build_release_matrix.sh`](../scripts/build_release_matrix.sh) immediately probes every staged `lib/*.so` with the **same matrix interpreters** used to compile (`FLASHCLI_PY310_BIN`, etc. from `install_python_for_matrix.sh`):

1. **Per cell** — `_bundle_build.sh` probes the just-built artifacts; **ABI mismatch (`rc=2`) fails the build**.
2. **Post matrix** — `verify_native_lib_python_abi` (in [`scripts/lib/verify_native_abi.sh`](../scripts/lib/verify_native_abi.sh)) re-checks the merged `lib/` before pack.

Docker builds persist interpreters on the mounted workspace (`/workspace/.flashcli-python`, `/workspace/.flashcli/python-matrix.env`) so later host `pack_bundle.sh` can reuse them:

```bash
source ../.flashcli/python-matrix.env   # from workspace root, sibling of flashcli/
bash scripts/pack_bundle.sh --bundle-dir bundles/qwen_nvfp4 --repo-root ../FlashRT
```

**Host pack without matrix Python** still works (matrix file check runs; ABI probe warns and skips). Compile-time verify is the gate; `flashcli bundle validate` remains optional.

Docker images (defaults in `release-matrix.env`):

| CUDA line | Default image |
|-----------|---------------|
| cu124 | `nvcr.io/nvidia/pytorch:24.05-py3` (nvcc 12.4) |
| cu130 | `nvcr.io/nvidia/pytorch:25.10-py3` (nvcc 13.x) |

---

## pi05_libero

**Supported GPU**: **SM89 only** (Ada). Artifacts are labeled **sm89** (`GPU_ARCH=89`); `requires.sm` is `["89"]`.

| CUDA line | FA2 build strategy | Notes |
|-----------|-------------------|-------|
| **cu124** (nvcc 12.4) | `FA2_ARCH_NATIVE_ONLY` → sm_89 AOT only | Default for CUDA 12.4 userland |
| **cu130** (nvcc 13.x) | Default sm_80 + sm_120 + PTX in FA2 | Kernels remain sm_89; for SM89 hosts on CUDA 13 |

SM120 / Blackwell is **not supported** for pi05 yet. For local SM89-only dev (not for release): `build.sh --fa2-native-only`.

### Release build

**One command (Docker, recommended):**

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean
# equivalent: cd bundles/pi05_libero && bash release.sh --clean
```

**Background + log:**

```bash
bash scripts/run_bg.sh --name release-pi05 -- \
  bash scripts/release_bundle.sh --bundle pi05_libero --clean
bash scripts/run_bg.sh --name release-pi05 --tail
```

**Step-by-step (host with both CUDA toolkits, no Docker):**

```bash
bash scripts/build_release_matrix.sh --bundle pi05_libero --check-only
bash scripts/release_bundle.sh --bundle pi05_libero --clean --cuda-tag 124
bash scripts/release_bundle.sh --bundle pi05_libero --cuda-tag 130
flashcli bundle validate bundles/pi05_libero
```

**Single cell (maintainer dev):**

```bash
bash scripts/build_release_matrix.sh --bundle pi05_libero \
  --cuda-tag 124 --python-minor 312 --skip-pack
```

**Local single-environment dev:**

```bash
cd bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
```

Upload `bundles/pi05_libero/dist/*.zip` to CDN; update `models.yaml` → `pi05_libero.bundle.zip`.

Host key example: `sm89-cu124-linux-x86_64-py312`. Check: `flashcli models envs pi05_libero`.

---

## qwen_nvfp4 (SM120 × cu130)

NVFP4 / sm_120a kernels **require nvcc ≥ 12.8**. The **cu124 + 24.05-py3** container cannot build qwen — the matrix is **cu130 only**.

One zip serves two catalog presets (`qwen3-8b-nvfp4`, `qwen36-27b-nvfp4`); weights are fetched from Hugging Face, not shipped in the zip.

### Release build

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
# equivalent: cd bundles/qwen_nvfp4 && bash release.sh --clean
```

Requires **Linux + Docker + GPU** (or `--native` with CUDA 13 toolkit on host). Default container: `nvcr.io/nvidia/pytorch:25.10-py3`.

Artifact example:

```text
bundles/qwen_nvfp4/dist/flashcli-bundle-qwen_nvfp4-{abi}-sm120-multi-linux-x86_64-{timestamp}.zip
```

Update **both** Qwen presets in `models.yaml` with the same `bundle.zip` URL.

Host key example: `sm120-cu130-linux-x86_64-py312`. Check: `flashcli models envs qwen3-8b-nvfp4`.

---

## Runtime selection (end users)

| Stage | What gets installed |
|-------|---------------------|
| `install.sh` / `pip install flashcli` | flashcli CLI only |
| `flashcli run` | torch from bundle `python_dependencies` → matching `lib/*.so` |

Do not run Python 3.12 against a bundle that only contains `-py310` artifacts — activation fails with an ABI mismatch.

## Local debug (no CDN)

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

Catalog and bundle format: [model_bundle_standard.md](model_bundle_standard.md). Contributing and release workflow: [../CONTRIBUTING.md](../CONTRIBUTING.md).
