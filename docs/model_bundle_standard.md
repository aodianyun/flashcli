# Model Bundle — preset ref and runtime flow

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

For **integrators** wiring presets to FlashHub. Full manifest / entry / `.so` spec → **[bundle_publish_standard.md](bundle_publish_standard.md)**.

## Discovering bundles (FlashHub)

Published Model Bundles live on **[FlashHub](https://flashhub.top)**. Pick a repo/version there, then pass its ref to flashcli. There is **no bundled catalog file** in the flashcli repo.

`flashcli models list` shows **locally cached** refs with bundle/weights disk usage (after `run`, `serve`, `pull`, or `bundle sync`).

## Preset ref (FlashHub)

```text
namespace/bundle:version
```

Examples:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.5
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0
```

| Part | Meaning |
|------|---------|
| `namespace/bundle:version` | FlashHub repo slug + pinned version |
| Full URL | `https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.5` also accepted |

**API base** (env): `FLASHCLI_FLASHHUB_API` (default `https://flashhub-api.aodianyun.com/api/v1/repos`).  
Browse published bundles on **[flashhub.top](https://flashhub.top)** — the public site; the API is not yet served on that domain.  
Resolved repo URL: `{FLASHCLI_FLASHHUB_API}/{namespace}/{bundle}:{version}`.

**Local dev** (positional; directory must contain `flashcli-bundle.json`):

```bash
flashcli run bundles/pi05_libero
flashcli pull bundles/pi05_libero
```

## Environment selection

The host first matches an exact `environments.<env>` key. If none matches, it evaluates fallback entries by their `match` dimensions (`os`, `arch`, `python_abi`, optional `vendor`, `sm`, `cuda`); more matching dimensions win. A second environment may share the same runtime directory. A runtime-less environment is pure Python/CPU fallback.


## After sync

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py / serve.py
├── flash_rt/
└── runtime/<runtime-dir>/      # FlashHub sync; load .so from here at runtime
```

> Native-only bundles (`defaults.entry.kind = native-abi|native-exec`) omit `run.py`/`serve.py` and `flash_rt/`; C libraries live under `runtime/<runtime-dir>/substrate/`.

Weights are **not** in the bundle. v4 uses a readable shared store keyed by `source + repo + revision` (normally `~/.flashcli/models/store/...`); extra weights default to `<store>/extra/<key>/`.

## End-user runtime flow

1. Parse REF → local directory uses `local_root`; otherwise `bundle.repo` URL (or synced marker)
2. FlashHub manifest → **preflight** env key on this host
3. Download entry tree + **only** matching `runtime/<runtime-dir>/`
4. `kind=python`: create bundle venv (`python_abi`, manifest torch). Native kinds skip the venv.
5. `kind=python`: **re-exec** infer inside the bundle venv — [architecture.md](architecture.md). `native-exec`/`native-abi`: the host spawns / `dlopen`s the bundle backend directly.
6. **Host** (before inference): ensure `weights` + `extra_weights` + `post_pull`. The host writes the expected remote file set to `<weights_dir>/.flashcli_download.json` **before** transferring, resumes interrupted downloads, and accepts a complete manifest offline; `flashcli pull` re-lists and rewrites it. 7. **Bundle**: resolve local checkpoint only (`HF_HUB_OFFLINE=1`); run `entry` (or the native backend)

`flashcli pull <ref>` runs steps 1–6 without inference. First `flashcli run` / `serve` also runs 1–6 automatically when cache is cold.

`flashcli bundle sync <ref>` pre-fetches the FlashHub tree only (no weights).

**Environment and weights source** (`flashcli models show <ref>`): the host selects an exact environment or matching fallback from `flashcli-bundle.json`; weights `source`/`repo`/`revision` come from the same manifest. Multiple environments may share one runtime directory.

## Execution backends (`entry.kind`)

A bundle's `entry` selects how flashcli invokes inference. The user command is unchanged either way:

| `entry.kind` | Backend |
|--------------|---------|
| `python` (default) | bundle venv re-exec → `python -m flashcli_bundle.infer` |
| `native-exec` | host spawns a bundle executable (NDJSON stdio / HTTP) |
| `native-abi` | host `dlopen`s an `frt_model_runtime_v1` `.so` and drives it in-process |

Bundles without `entry.kind` behave exactly as before. Full contract: [bundle_execution_abi.md](bundle_execution_abi.md).

## Quick checks

```bash
flashcli models list          # cached refs + per-ref bundle/weights usage
flashcli models show <ref>
flashcli du                   # total bundles/models/runtimes/cache usage
flashcli bundle validate /path/to/bundle
flashcli run <ref> --help
```
