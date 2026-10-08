# flashcli module layers

Three runtime layers share one protocol package (`flashcli-bundle`). This document is the checklist for where code belongs and what each layer may import.

<p align="right"><strong>English</strong> · <a href="module_layers.zh-CN.md">简体中文</a></p>

## Module placement rule (read this first)

**Ask who imports the module before choosing a home:**

| Used by | Lives in | Do not put in |
|---------|----------|---------------|
| **Host only** (Go `flashcli`) | `go/internal/` | `flashcli_bundle/` |
| **Infer only** (`flashcli_bundle.infer`) | `flashcli_bundle/infer/` | `flashcli_bundle/` protocol root |
| **Both host and infer** | `flashcli_bundle/` (protocol) | duplicated copies in host/infer |

```text
host only  → go/internal/
infer only → flashcli_bundle/infer/
both       → flashcli_bundle/ (protocol, dependencies = [])
```

**Re-export is not a reason to add protocol code.** Thin re-exports exist only for stable import paths. If only one layer needs the logic, implement it in that layer.

**Protocol must not contain** (even with `dependencies = []`):

- Host-only: Hugging Face weight download, `huggingface_hub`, GitHub release download, standalone Python install/probe, FlashHub sync assembly, re-exec
- Infer-only: FastAPI/uvicorn, engine loader, HTTP serve stack, bundle Typer entry

**Shared orchestration allowed in protocol** (host/infer inject deps via callbacks):

- `activate_core.py`, `cache.py`, `post_pull.py`, resolve paths in `weights.py` / `resolve.py` — the Go host injects HF/ModelScope download and per-file `extra_weights` fetch.

**Host-only code** lives in `go/internal/` (Go). Examples: `weights` (HF/ModelScope download, `post_pull`), `flashhub` (sync), `venv`/`pythonprovision`, `inferexec`/`nativeexec`/`nativeabi`, `cli`.

## Layer overview

| Layer | Language / install | May import | Must not import |
|-------|--------------------|------------|-----------------|
| **Protocol** | Python `flashcli-bundle` (`dependencies = []`) | `flashcli_bundle.*` (except `infer`) | fastapi/uvicorn/torch, `flashcli_bundle.infer` |
| **Host** | Go binary (`go/`) | `flashcli_bundle.*` (protocol) at the exec boundary | `flashcli_bundle.infer` |
| **Infer** | Python `flashcli-bundle[infer]` + manifest deps | `flashcli_bundle.*` (incl. `infer`) | `huggingface_hub` (weight download) |

```text
Host (Go)  ──re-exec/exec──►  flashcli_bundle.infer ──► flashcli_bundle (protocol + [infer])
```

The Go host never imports the Python infer package; it starts it as a subprocess (or drives a native backend).

## Protocol modules (`flashcli_bundle/`)

Canonical home for shared types, manifest/options, paths, FlashHub client, preset/weights/cache logic (no HTTP serve stack, no HF hub).

| Module | Role |
|--------|------|
| `protocol.py` | `RunEngine` / `ServeEngine` / request types |
| `manifest.py`, `manifest_ext.py` | Manifest load + layout validation |
| `manifest_resolve.py`, `help_text.py` | Help-only manifest resolution |
| `options.py`, `catalog.py`, `preset.py`, `preset_ref.py` | Ref parsing, preset view |
| `paths.py`, `marker.py`, `context.py`, `errors.py` | Paths, markers, activation context |
| `flashhub.py`, `flashhub_errors.py` | FlashHub index/manifest download |
| `openai_compat.py` | OpenAI-compat helpers (no starlette) |
| `native*.py`, `layout.py`, `variants.py`, `checkpoint.py`, `weights_spec.py` | Bundle layout + checkpoint rules |
| `runtime/detect.py`, `runtime/requirements_spec.py`, `runtime/mirror.py` | GPU/CUDA, pip specs, mirrors |
| `util/download_progress.py` | HTTP download (lazy tqdm) |
| `cache.py`, `post_pull.py`, `resolve.py`, `weights.py` (resolve), `activate_core.py` | Shared when both layers import; download/HF stays host |

**Not protocol (host-only):** weight download, FlashHub sync assembly, venv provisioning, re-exec — all in `go/internal/`.

## Host (Go, `go/internal/`)

Command tree, FlashHub sync, weight download, preflight, venv, and backend dispatch. Never imports Python infer code.

| Package | Role |
|---------|------|
| `cli` | User-facing commands (`run`/`serve`/`pull`/`bundle`/`models`/`doctor`/`upgrade`) |
| `ref`, `flashhub` | Ref parsing, FlashHub index + tree sync |
| `weights` | HF/ModelScope download, cache, `post_pull`, `extra_pull` |
| `preflight`, `native`, `hostabi`, `cuda` | Env-key match, native cell validation, host ABI, CUDA userland |
| `venv`, `pythonprovision` | Bundle venv creation + base Python provisioning |
| `inferexec`, `nativeexec`, `nativeabi` | Execution backends (`entry.kind`) |
| `manifest` | Manifest parse + validation |
| `paths`, `runtime`, `selfupdate`, `postpull`, `version`, `errs` | Support |

## Infer modules (`flashcli_bundle/infer/`)

Bundle venv entry: `python -m flashcli_bundle.infer run|serve`.

| Module | Role |
|--------|------|
| `__main__.py`, `app.py`, `cli.py` | Bundle argv + dispatch |
| `engines/*`, `serve/*` | Engine load + FastAPI/uvicorn |
| `deps.py`, `runtime/bundle_venv.py` | Bundle venv pip (read-only paths) |
| `bundle/resolve.py` | `activate_for_preset` (infer activation path) |

**Re-export only** (shared protocol): `preset.py`, `preset_ref.py`, `cache.py`, `runtime/detect.py`, `runtime/mirror.py` (pip/HF only), etc.

**Infer-only wrappers**: `bundle/weights.py`, `bundle/activate.py`.

## Enforcement

- **Protocol** `flashcli-bundle/pyproject.toml` keeps `dependencies = []`; the infer extra includes the serve stack and excludes `huggingface_hub`.
- **Execution ABI / host parity** is enforced by `tests/conformance/` (command-surface parity, Py↔Go execution-ABI agreement, re-exec/native backends).
- **Go host** packages are checked by `go test ./...` (manifest/native/preflight/weights/venv/backends).
- The Python host (`src/flashcli/`) was removed; do not reintroduce host-only code under `flashcli_bundle/`.

See also [architecture.md](architecture.md) for runtime flow and directory layout.
