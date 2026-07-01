# Model Bundle — preset ref and runtime flow

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

For **integrators** wiring presets to FlashHub. Full manifest / entry / `.so` spec → **[bundle_publish_standard.md](bundle_publish_standard.md)**.

## Discovering bundles (FlashHub)

Published Model Bundles live on **[FlashHub](https://flashhub.top)**. Pick a repo/version there, then pass its ref to flashcli. There is **no bundled catalog file** in the flashcli repo.

`flashcli models list` shows **locally cached** refs only (after `run`, `serve`, `pull`, or `bundle sync`).

## Preset ref (FlashHub)

```text
namespace/bundle:version[@variant]
```

Examples:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36
```

| Part | Meaning |
|------|---------|
| `namespace/bundle:version` | FlashHub repo slug + pinned version |
| `@variant` | Optional; selects `variants.*` in manifest (e.g. Qwen3 vs Qwen3.6) |
| Full URL | `https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.4` also accepted |

**API base** (env): `FLASHCLI_FLASHHUB_API` (default `https://flashhub-api.aodianyun.com/api/v1/repos`).  
Browse published bundles on **[flashhub.top](https://flashhub.top)** — the public site; the API is not yet served on that domain.  
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
6. **Host** (before re-exec): download `weights` + `extra_weights` + `post_pull` if cache is incomplete — same code path as `flashcli pull`
7. **Bundle venv**: resolve local checkpoint only (`HF_HUB_OFFLINE=1`); run `entry`

`flashcli pull <ref>` runs steps 1–6 without inference. First `flashcli run` / `serve` also runs 1–6 automatically when cache is cold.

`flashcli bundle sync <ref>` pre-fetches the FlashHub tree only (no weights).

**Env key** (`flashcli models envs <ref>`): `sm{SM}-cu{CUDA}-linux-x86_64-py{PY}`.

## Quick checks

```bash
flashcli models list          # locally cached refs only
flashcli models envs <ref>
flashcli bundle validate /path/to/bundle
flashcli run <ref> --help
```
