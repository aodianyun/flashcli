# Bundle manifest policy (`flashcli-bundle.json`)

## Principle

**`flashcli-bundle.json` is authoritative, complete, and maintained only by the bundle publisher.**

Build, pack, release, and flashcli tooling **must not modify, overwrite, or auto-sync** the publisher’s
`bundles/<name>/flashcli-bundle.json`. Treat it like application source code: edit in git, review in PRs.

Publishers own all author fields, including at minimum:

- `name`, `description`, `entry`, `run_options`, `serve_options`
- `python_dependencies` (torch index, pip pins such as `transformers>=4.57.0`)
- `weights` / variants / `env`
- Any other product-facing defaults

## Generated artifacts (not in git)

| File | Written by | Purpose |
|------|------------|---------|
| `.build/manifest-overlay.json` | `build.sh` / matrix finalize | Build metadata: `runtime` map scan, `build`, `python_abi` |
| `dist/flashcli-bundle.json` | `pack_bundle.sh` | **Publishable** manifest = author manifest + overlay + per-env `runtime/` layout |

End users and FlashHub consume **`dist/flashcli-bundle.json`**, not the mutable overlay alone.

## Script contracts

### Matrix cell (`_bundle_build.sh`)

- MAY add/update tagged `.so` under `lib/`
- MUST NOT modify `flashcli-bundle.json`
- MAY write `.build/manifest-overlay.json` when not using `--skip-manifest`

### Finalize (matrix)

- MUST scan `lib/*.so` and refresh `.build/manifest-overlay.json`
- MUST NOT modify `flashcli-bundle.json`

### Pack (`scripts/pack_bundle.sh`)

- MUST read `bundles/<name>/flashcli-bundle.json` as read-only input
- MAY merge `.build/manifest-overlay.json` and `lib/*.so` → `runtime/`
- MUST write merged manifest **only** under `dist/flashcli-bundle.json`
- MUST NOT write back to the bundle source tree manifest

### `generate_runtime_manifest.py`

- `--bundle-json` is **read-only** input
- `--output-json` is **required** (typically `.build/manifest-overlay.json`)
- By default writes overlay fields only (`runtime`, `build`, `python_abi`); use `--full-manifest` for dist merges
- MUST NOT sync `python_dependencies` from FlashRT unless `--sync-python-dependencies` is passed (deprecated)

## Publisher workflow

1. Edit `flashcli-bundle.json` by hand (deps, weights, options).
2. `bash bundles/<name>/build.sh` → native libs + `.build/manifest-overlay.json`.
3. `bash scripts/pack_bundle.sh --bundle-dir bundles/<name>` → `dist/` for upload / local run.
4. Validate and run against **`dist/`**:
   `flashcli bundle validate bundles/<name>/dist`

## Rationale

Earlier tooling treated the manifest as a build artifact and overwrote `python_dependencies` from
FlashRT’s global `requirements/runtime-inference.txt` (`transformers<4.56` for Pi0.5). That broke
bundles with different requirements (e.g. Qwen3-VL needs `transformers>=4.57.0`). Separating author
manifest from generated overlay keeps publisher intent intact.
