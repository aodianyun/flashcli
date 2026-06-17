# flashcli module layers

Three runtime layers share one protocol package (`flashcli-bundle`). This document is the checklist for where code belongs and what each layer may import.

<p align="right"><strong>English</strong> · <a href="module_layers.zh-CN.md">简体中文</a></p>

## Module placement rule (read this first)

**Ask who imports the module before choosing a home:**

| Used by | Lives in | Do not put in |
|---------|----------|---------------|
| **Host only** (`flashcli`) | `src/flashcli/` | `flashcli_bundle/` |
| **Infer only** (`flashcli_bundle.infer`) | `flashcli_bundle/infer/` | `flashcli_bundle/` protocol root |
| **Both host and infer** | `flashcli_bundle/` (protocol) | duplicated copies in host/infer |

```text
host only  → src/flashcli/
infer only → flashcli_bundle/infer/
both       → flashcli_bundle/ (protocol, dependencies = [])
```

**Re-export is not a reason to add protocol code.** Thin re-exports exist only for stable import paths. If only one layer needs the logic, implement it in that layer — do not land it in protocol first.

**Protocol must not contain** (even with `dependencies = []`):

- Host-only: Hugging Face weight download, `huggingface_hub`, GitHub release download, standalone Python install/probe, FlashHub sync assembly, re-exec
- Infer-only: FastAPI/uvicorn, engine loader, HTTP serve stack, bundle Typer entry

**Shared orchestration allowed in protocol** (host/infer inject deps via callbacks):

- `activate_core.py`, `cache.py`, `post_pull.py`, resolve paths in `weights.py` / `resolve.py`

### Known migration backlog (Phase 2 complete)

| Module / API | Status |
|--------------|--------|
| ~~`python_paths.py`~~ | ✅ `src/flashcli/bundle/python_paths.py` |
| ~~`resolve_python_for_minor`~~ | ✅ `src/flashcli/bundle/python_resolve.py` |
| ~~GitHub release download~~ | ✅ `src/flashcli/runtime/mirror_github.py` |
| ~~Weight download orchestration~~ | ✅ `src/flashcli/bundle/weights.py` (protocol resolve-only) |

New protocol modules require imports from **both** host and infer trees.

## Layer overview

| Layer | pip install | May import | Must not import |
|-------|-------------|------------|-----------------|
| **Protocol** | `flashcli-bundle` (`dependencies = []`) | `flashcli_bundle.*` (except `infer`) | `flashcli`, fastapi/uvicorn/torch, `flashcli_bundle.infer` |
| **Host** | `flashcli` + `flashcli-bundle` | `flashcli.*`, `flashcli_bundle.*` (protocol) | `flashcli_bundle.infer` |
| **Infer** | `flashcli-bundle[infer]` + manifest deps | `flashcli_bundle.*` (incl. `infer`) | `flashcli`, `huggingface_hub` (weight download) |

```text
Host venv:     flashcli ──► flashcli_bundle (protocol)
Bundle venv:   flashcli_bundle.infer ──► flashcli_bundle (protocol + [infer] extra)
```

Host and infer must never cross-import each other.

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

**Not protocol (host-only examples):** `models/pull.py`, `bundle/artifacts.py`, `runtime/reexec.py`, `bundle/python_install.py`, GitHub release mirror helpers (target: host).

## Host modules (`flashcli/`)

Typer CLI, HF weight download, bundle sync/distribution, re-exec into bundle venv.

| Module | Role |
|--------|------|
| `cli.py`, `doctor.py` | User-facing commands |
| `models/pull.py`, `models/hf_hub.py` | Hugging Face weight download (host only) |
| `bundle/artifacts.py`, `preflight.py`, `python_install.py` | Runtime assembly |
| `runtime/reexec.py`, `runtime/bundle_venv.py` | Re-exec + venv creation |
| `deps.py` | Host pip (`FLASHCLI_HOST_PACKAGES` + plain `flashcli-bundle`) |
| `bundle/run_help.py`, `bundle/run_argv.py` | Manifest-only help + host flags |

**Re-export only** (no duplicate logic): `config.py`, `models/registry.py`, `models/preset_ref.py`, `bundle/marker.py`, `bundle/catalog.py`, `bundle/manifest.py`, `runtime/detect.py`, `runtime/requirements_spec.py`, `runtime/mirror.py`, `util/download_progress.py`, `models/cache.py`, `models/post_pull.py`, `bundle/resolve.py`.

**Host-only wrappers**: `bundle/weights.py` (injects HF download), `bundle/activate.py` (injects host deps + venv).

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

Structural rules live in `tests/test_architecture_layers.py`:

- Host tree never imports `flashcli_bundle.infer`
- Protocol `pyproject.toml` has `dependencies = []`
- Infer extra includes serve stack, excludes `huggingface_hub`
- Listed re-export modules must not duplicate protocol implementations
- `Preset` exposes `engine` and `description`
- **Placement rule:** new protocol modules must be imported from both host and infer; `HOST_ONLY_PROTOCOL_MODULES` allowlist must not grow
- Infer `runtime/mirror` must not re-export GitHub release download APIs

See also [architecture.md](architecture.md) for runtime flow and directory layout.
