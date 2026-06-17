# Model Bundle — preset ref and runtime flow

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

For **integrators** wiring presets to FlashHub. Full manifest / entry / `.so` spec → **[bundle_publish_standard.md](bundle_publish_standard.md)**.

## Preset ref (FlashHub)

Users pass a **ref string** instead of a bundled catalog file:

```text
namespace/bundle:version[@variant]
```

Examples:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36
```

| Part | Meaning |
|------|---------|
| `namespace/bundle:version` | FlashHub repo slug + pinned version |
| `@variant` | Optional; selects `variants.*` in manifest (e.g. Qwen3 vs Qwen3.6) |
| Full URL | `https://flashhub-api…/flashcli-bundle/pi05_libero:1.0.3` also accepted |

**API base** (env): `FLASHCLI_FLASHHUB_API` (default `https://flashhub-api.aodianyun.com/api/v1/repos`).  
Resolved repo URL: `{FLASHCLI_FLASHHUB_API}/{namespace}/{bundle}:{version}`.

**Local dev** (positional; directory must contain `flashcli-bundle.json`):

```bash
flashcli run bundles/qwen_nvfp4@qwen36
flashcli pull bundles/qwen_nvfp4@qwen36
```

Multi-variant bundles **require** `@variant` in the ref.

## After sync

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<env-key>/      # FlashHub sync; load .so from here at runtime
```

Weights are **not** in the bundle; cached under `~/.flashcli/models/<bundle>/<version>@<variant>/`.

## End-user runtime flow

1. Parse REF → local directory uses `local_root`; otherwise `bundle.repo` URL (or synced marker)
2. FlashHub manifest → **preflight** env key on this host
3. Download entry tree + **only** matching `runtime/<env-key>/`
4. Create bundle venv (`python_abi`, manifest torch)
5. **Re-exec** infer inside bundle venv — [architecture.md](architecture.md)
6. Activate → HF weights → `entry`

`flashcli bundle sync <ref>` pre-fetches; first `run` / `serve` syncs automatically.

**Env key** (`flashcli models envs <ref>`): `sm{SM}-cu{CUDA}-linux-x86_64-py{PY}`.

## Quick checks

```bash
flashcli models list          # locally cached refs only
flashcli models envs <ref>
flashcli bundle validate /path/to/bundle
flashcli run <ref> --help
```
