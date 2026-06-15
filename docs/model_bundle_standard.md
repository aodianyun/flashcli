# flashcli Model Bundle standard

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

Third parties ship models as a **Model Bundle**: one **`flashcli-bundle.json`**, **`entry` inference modules**, and optional **FlashRT `.so` / `flash_rt` Python**. flashcli **only** loads the bundle and calls `entry`; it does **not** implement Run/Serve logic in flashcli source.

**External publish standard** (layout, manifest, entry, `.so` naming, FlashHub tree) → **[bundle_publish_standard.md](bundle_publish_standard.md)**

Internal maintainer workflow (build, pack, flashcli commands) → [bundle_builder_guide.md](bundle_builder_guide.md). Public catalog: [`models.yaml`](../src/flashcli/catalog/models.yaml).

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
      repo: https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/my_model:1.0.0
      # path: bundles/my_bundle   # local dev
    # bundle_variant: qwen3        # when several presets share one repo
```

- **`bundle.repo`** — FlashHub semantic API. Catalog uses `flashhub-api.aodianyun.com` with `model:version` (colon). Response includes `data.files[]` with `download_url`, `file_size`, `md5_hash`.
- **`bundle.path`** — local bundle tree for development.
- **`bundle_variant`** — when several presets share one repo (e.g. Qwen3 vs Qwen3.6 weights).

## `flashcli-bundle.json` (v3)

| Field | Description |
|-------|-------------|
| `format_version: 3` | Only supported manifest schema version |
| `protocol_version: 1` | **flashcli-bundle** API version (**required**; must match installed `flashcli-bundle`) |
| `name` | Bundle id (matches directory / release name) |
| `description` | Human-readable summary (recommended) |
| `python_abi` | Fixed Python ABI for this bundle (e.g. `312` = 3.12); bundle venv uses this interpreter |
| `runtime` | `{env_key: path}` — usually `runtime/<env-key>/` with that env’s `.so` files |
| `entry` | `run` / `serve` module + class |
| `python_dependencies` | `torch` (may be `{package, index}`) + `pip` list |
| `run_options` | CLI options for `flashcli run` (see below) |
| `serve_options` | CLI options for `flashcli serve` (see below) |
| `variants` | Per-variant weights + options when one repo serves multiple presets |
| `weights` / `post_pull` | Hugging Face (or in-bundle) weights and post-download steps |

Environment key: `sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}` (`PY` from `python_abi`). Capabilities are inferred from `entry`.

### PyTorch wheel index

Use `"index": "auto"` so flashcli picks `cu124` or `cu128` from the host’s matched runtime env key (SM89 cu124 → cu124; SM120 / cu130 → cu128). Do **not** hard-code `cu128` unless the bundle truly requires one CUDA line only.

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": ["numpy", "transformers<4.56"]
}
```

### `run_options` and `serve_options`

Bundle-specific flags are declared in the manifest. flashcli builds `--help` and parses argv from these lists; defaults live in each option’s `"default"` field (there is **no** separate top-level `defaults` block).

| Command | Manifest key | Phases passed to `RunEngine` / `ServeEngine` |
|---------|--------------|------------------------------------------------|
| `flashcli run` | `run_options` | `load` → `load()`; `predict` → `predict()` |
| `flashcli serve` | `serve_options` | `load` → `load()`; `warmup` → warmup step |

Each option object:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Python kwarg name (snake_case) |
| `type` | no | `string` (default), `integer`, `float`, `boolean` |
| `default` | no | Default when the flag is omitted |
| `help` | yes | Shown in `flashcli run PRESET --help` / `flashcli serve PRESET --help` |
| `phase` | no | `load` or `predict` (run); `load` or `warmup` (serve). Default: `predict` / `load` |
| `flag` | no | CLI flag without `--` (default: `name` with `_` → `-`) |

**flashcli-owned flags** (not in manifest): `run` — `--bundle`, `--checkpoint`, `--benchmark`, `--warmup`, …; `serve` — `--host`, `--port`, …

Users discover bundle flags:

```bash
flashcli run pi05_libero --help
flashcli serve qwen3-8b-nvfp4 --help
```

### Variants (multi-preset repo)

When `variants` is present, **each variant must define its own** `run_options` and/or `serve_options` (matching `entry`). Top-level `run_options` / `serve_options` are **forbidden** and fail validation.

Catalog presets point at the same `bundle.repo` and differ by `bundle_variant`:

```yaml
qwen3-8b-nvfp4:
  bundle_variant: qwen3
  bundle:
    repo: …/qwen_nvfp4/1.0.1
qwen36-27b-nvfp4:
  bundle_variant: qwen36
  bundle:
    repo: …/qwen_nvfp4/1.0.1
```

Variant block fields (typical): `description`, `weights`, `weights_dir`, `extra_weights`, `env`, `run_options`, `serve_options`.

Full manifest examples: [bundle_publish_standard.md](bundle_publish_standard.md) §3.8 and repo files `bundles/pi05_libero/flashcli-bundle.json`, `bundles/qwen_nvfp4/flashcli-bundle.json`.

## FlashHub publish

`bash scripts/pack_bundle.sh --bundle-dir bundles/<name>` produces under `dist/`:

- `flashcli-bundle.json`, `run.py`, `flash_rt/`, … (bundle source tree)
- `runtime/<env-key>/` — native `.so` per supported GPU/CUDA env

`pack_bundle.sh` refreshes the manifest `runtime` map from built `lib/*.so`; it does **not** remove `run_options` / `serve_options`.

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
- Classes implement `RunEngine` / `ServeEngine` from **`flashcli_bundle.protocol`** (see [flashcli-bundle/README.md](../flashcli-bundle/README.md)).
- Read defaults via `run_option_defaults()` / `serve_option_defaults()` and `option_value()` from **`flashcli_bundle`** (pip package `flashcli-bundle`). Do **not** duplicate literal defaults in `run.py` / `serve.py`.
- All inference logic stays inside the bundle.

## Validation

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --help
flashcli serve qwen3-8b-nvfp4 --help
```

Validation checks manifest schema, options layout (variants vs top-level), weights spec, and (when present) native runtime ABI under each declared env key.
