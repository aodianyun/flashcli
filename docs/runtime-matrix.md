# Runtime release matrix (pi05_libero)

<p align="right"><strong>English</strong> · <a href="runtime-matrix.zh-CN.md">简体中文</a></p>

## Urgent maintenance scope

| Dimension | Values |
|-----------|--------|
| SM | **89** (SM120 uses catalog aliases to SM89 zips) |
| CUDA userland | **cu124**, **cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12** (`-py310` / `-py311` / `-py312`) |

**6 separate CDN zips** — each cell compiles `flash_rt_*.so` for one Python ABI.

Catalog: [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml).

## What the matrix script does

- **Loops** `cu124|130` × `py310|311|312`, runs cmake + pack per cell.
- **Does not** install CUDA; set `CUDA_HOME_CU124` / `CUDA_HOME_CU130` before each line.
- **Does not** install Python by default; use `--install-python` (apt) or `FLASHCLI_PY312_BIN=...`.
- **`--cuda-tag`** switches toolkit via `CUDA_HOME` and checks `nvcc` matches the tag (not zip rename only).

## Fast path

```bash
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4
bash scripts/build_pi05_release_matrix.sh --check-only

# 3 zips if you only have CUDA 12.4 today:
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124

# later, 3 cu130 zips:
export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_pi05_release_matrix.sh --cuda-tag 130
```

Upload `bundles/pi05_libero/dist/*.zip` to CDN and verify URLs in `models.yaml`.

## Runtime selection

`flashcli run` picks a variant from **GPU + current Python** (`host_python_minor()`).  
Check match: `flashcli models envs pi05_libero`.

Example (RTX 4060 Ti + Python 3.12 + driver CUDA 12.4):

```text
sm89-cu124-linux-x86_64-py312
```

Do not load a `-py310` zip with Python 3.12 — activation fails with an ABI mismatch error.
