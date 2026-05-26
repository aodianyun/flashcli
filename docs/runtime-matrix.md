# Runtime release matrix (pi05_libero)

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

## Current maintenance scope

| Dimension | Values |
|-----------|--------|
| SM | **89** (SM120 runs SM89 artifacts when `requires.sm` allows) |
| CUDA userland | **cu124**, **cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12** (`-py310` / `-py311` / `-py312`) |

## Recommended: one zip, many environments (`native_layout: matrix`)

One **runtime zip per model**; all environment-specific `.so` files live under flat **`lib/`**:

```text
pi05_libero/
  flashcli-bundle.json    # native_layout: matrix, native_matrix: [...]
  lib/
    flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py310.so
    flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py310.so
    ... py311, py312, cu130, ...
  flash_rt/
  run.py
```

At **`flashcli run`**, flashcli picks the artifact matching **GPU + current Python** under `lib/`; no match → `NativeEnvironmentNotSupportedError`.

**`models.yaml` no longer uses `bundle.variants`** — one `bundle.zip` per preset (`schema_version: 6`).

Build cu124 × three Python ABIs into one zip:

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
```

Catalog: [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml). Bundle format: [model_bundle_standard.md](model_bundle_standard.md).

---

## Legacy: one zip per environment (still supported)

**Six separate CDN zips** were used previously (one Python ABI per zip). The naming rules below still apply to artifacts inside `lib/` or standalone releases.

### Native `.so` naming

```text
{module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

Example: `flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

## What the matrix script does

| Capability | `build_pi05_release_matrix.sh` |
|------------|--------------------------------|
| Loop cu124/130 × py310/311/312 | ✓ |
| Install Python 3.10–3.12 | ✗ by default; optional `--install-python` |
| Switch CUDA toolkit | ✓ via `CUDA_HOME_CU124` / `CUDA_HOME_CU130` |
| `--cuda-tag` | Verifies `nvcc` matches the tag; writes manifest / zip name |

Each cell uses a **fresh build dir + full cmake** when building separate legacy zips.

## Fast path

```bash
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4
bash scripts/build_pi05_release_matrix.sh --check-only

bash scripts/build_pi05_release_matrix.sh --cuda-tag 124

export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_pi05_release_matrix.sh --cuda-tag 130
```

Upload `bundles/pi05_libero/dist/*.zip` to CDN and verify the URL in `models.yaml`.

## Runtime selection

Host key example (RTX 4060 Ti + Python 3.12 + CUDA 12.4 userland):

```text
sm89-cu124-linux-x86_64-py312
```

Check match: `flashcli models envs pi05_libero`

Do not run with Python 3.12 against a bundle that only contains `-py310` artifacts — activation fails with an ABI mismatch.

## Local debug (no CDN)

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

Build `.so` with the **same Python** you use to run flashcli.
