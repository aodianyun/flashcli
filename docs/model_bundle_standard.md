# Model Bundle — catalog & runtime flow

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

Short guide for **catalog integrators** wiring presets to FlashHub. Manifest, entry, and `.so` details → **[bundle_publish_standard.md](bundle_publish_standard.md)**.

## Catalog (`models.yaml`)

Source: [`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/my_model:1.0.0
      # path: bundles/my_bundle   # local dev
    # bundle_variant: qwen3        # when several presets share one repo
```

| Field | Purpose |
|-------|---------|
| `bundle.repo` | FlashHub API URL (`flashhub-api…`, `model:version`). Returns `data.files[]` for split download. |
| `bundle.path` | Local bundle tree (development only). |
| `bundle_variant` | Selects `variants.*` in manifest when one repo serves multiple presets (e.g. Qwen3 vs Qwen3.6). |

## Layout after sync

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<env-key>/      # synced from FlashHub; .so loaded in place at run time
```

Weights are **not** in the bundle; cached under `~/.flashcli/models/<preset>/`.

## End-user runtime flow

1. Resolve preset → `bundle.repo` (or `--bundle` / `path`)
2. FlashHub → `flashcli-bundle.json` → **preflight** env key vs manifest `runtime`
3. Download entry tree + **only** this host’s `runtime/<env-key>/`
4. Create bundle venv (`python_abi`, torch from manifest)
5. **Re-exec** infer in bundle venv (host flashcli on `PYTHONPATH`) — [architecture.md](architecture.md)
6. Activate bundle → HF weights → `entry` RunEngine / ServeEngine

`flashcli bundle sync <preset>` pre-fetches; first `run` / `serve` does this automatically.

**Env key** (check with `flashcli models envs <preset>`): `sm{SM}-cu{CUDA}-linux-x86_64-py{PY}` — e.g. `sm89-cu124-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`. `PY` matches manifest `python_abi` (currently `312`).

## Quick validation

```bash
flashcli models envs <preset>
flashcli bundle validate /path/to/bundle
flashcli run <preset> --help
```
