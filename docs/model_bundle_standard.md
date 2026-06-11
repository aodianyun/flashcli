# flashcli Model Bundle standard

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

Third parties ship models as a **Model Bundle**: one **`flashcli-bundle.json`**, **`entry` inference modules**, and optional **FlashRT `.so` / `flash_rt` Python**. flashcli **only** loads the bundle and calls `entry`; it does **not** implement Run/Serve logic in flashcli source.

Maintainers: see [CONTRIBUTING.md](../CONTRIBUTING.md). Public catalog: [`models.yaml`](../src/flashcli/catalog/models.yaml).

## Runtime layout (after sync)

```text
{bundle_root}/
├── flashcli-bundle.json    # format_version: 3
├── run.py / serve.py       # entry modules
├── flash_rt/               # FlashRT Python (no .so inside)
└── runtime/<env-key>/       # *.so for this host (from FlashHub sync)
```

Weights are **not** in the bundle; declared in `weights` and cached under `~/.flashcli/models/<preset>/`.

## Catalog (`models.yaml`)

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/my_model/1.0.0
      # path: bundles/my_bundle   # local dev
```

- **`bundle.repo`** — FlashHub semantic API (`/api/v1/repos/{org}/{model}/{version}`). Response includes `data.files[]` with `download_url`, `file_size`, `md5_hash`.
- **`bundle.path`** — local bundle tree for development.
- **`bundle_variant`** — when several presets share one repo (e.g. Qwen3 vs Qwen3.6 weights).

## `flashcli-bundle.json` (v3)

| Field | Description |
|-------|-------------|
| `format_version: 3` | Only supported version |
| `description` | Human-readable summary (recommended) |
| `python_abi` | Fixed Python ABI for this bundle (e.g. `312` = 3.12); bundle venv uses this interpreter |
| `runtime` | `{env_key: path}` — usually `runtime/<env-key>/` with that env’s `.so` files |
| `entry` | `run` / `serve` module + class |
| `python_dependencies` | `torch` (may be `{package, index}`) + `pip` list |
| `weights` / `post_pull` | Hugging Face (or in-bundle) weights and post-download steps |

Environment key: `sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}` (`PY` from `python_abi`). Capabilities are inferred from `entry`.

Example (`pi05_libero`):

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "name": "pi05_libero",
  "python_abi": "312",
  "entry": { "run": { "module": "run", "attr": "RunEngine" } },
  "python_dependencies": {
    "torch": { "package": "torch", "index": "cu128" },
    "pip": ["numpy", "transformers<4.56", "pillow"]
  },
  "weights": {
    "source": "huggingface",
    "repo": "lerobot/pi05_libero_finetuned_v044",
    "revision": "main"
  },
  "runtime": {
    "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
    "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"
  }
}
```

## FlashHub publish

`bash scripts/pack_bundle.sh --bundle-dir bundles/<name>` produces under `dist/`:

- `flashcli-bundle.json`, `run.py`, `flash_rt/`, … (bundle source tree)
- `runtime/<env-key>/` — native `.so` per supported GPU/CUDA env

Upload the entire `dist/` tree to FlashHub; set catalog `bundle.repo` to the semantic version URL.

## Runtime flow (end users)

1. `GET` FlashHub repo API → download `flashcli-bundle.json`
2. **Preflight** — host env key must match a key in `runtime` (fuzzy sm/cuda allowed)
3. Download bundle source tree + **only** this env’s `runtime/<env-key>/` artifacts
4. Create `~/.flashcli/runtimes/<id>/venv` (`python_abi`)
5. **Re-exec** — host CLI runs `bundle_venv/python …/infer_launch.py` (see [architecture.md](architecture.md))
6. Inside infer: **activate** bundle → load weights → call `entry`

At run time, layout validation checks **only the active env key** for this host (not every key listed in manifest `runtime`). Use `flashcli bundle validate PATH` to audit the full matrix (maintainers).

Command: `flashcli bundle sync <preset>` (or automatic on first `run` / `serve`).

See [runtime-matrix.md](runtime-matrix.md), [environment.md](environment.md).

## `entry` contract

- `entry.*.module` is relative to bundle root on `PYTHONPATH`.
- Classes implement `RunEngine` / `ServeEngine` ([`engines/base.py`](../src/flashcli/engines/base.py)).
- All inference logic stays inside the bundle.

## Validation

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
```
