# AGENTS.md

flashcli is the host CLI that distributes and runs FlashRT **Model Bundles**. It contains no model forward passes or CUDA kernels — those live in bundle `entry` modules and the sibling `FlashRT/` clone (build input only).

## Repo layout
- `go/` — the host (module `github.com/aodianyun/flashcli/go`): `cmd/flashcli` + `internal/*`. The Python host (`src/flashcli/`) was **removed**; do not reintroduce it.
- `flashcli-bundle/` — protocol + infer package (`flashcli_bundle`); separate `pyproject.toml`, `dependencies = []`, not on PyPI. Installed into bundle venvs as `flashcli-bundle[infer]`.
- `bundles/<name>/` — bundle **sources** only; published artifacts live on FlashHub, not in git.
- `scripts/` — build/release pipeline · `docs/` — authoritative specs · `tests/` — pytest.

## Dev setup
```bash
pip install -e "./flashcli-bundle"           # protocol (for pytest)
pip install -e "./flashcli-bundle[infer]"    # optional, to run infer subprocess tests
```
Go host needs Go >= 1.24. In CN networks set `GOPROXY=https://goproxy.cn,direct` (and `GOSUMDB=sum.golang.google.cn`). Module path: `go/`.

Distribution:
```bash
bash install.sh [--mirror]          # one-click host install (build-from-source, else release assets)
bash scripts/build_go.sh [OUT]      # cross-compile + sha256sums (version from pyproject)
bash scripts/release_go.sh [--upload]  # build, optionally publish to GitHub + Gitee
bash scripts/verify_release.sh [--version X]  # isolated install + smoke (never touches host state)
```
`install.sh` installs the `flashcli` binary (default: latest release assets + sha256; `--from-source` builds with Go) and writes `~/.flashcli/install.env` (bundle venv source: local checkout or repo/ref). Missing OS tools are auto-installed via the package manager. `auto_install.sh` picks GitHub/Gitee by reachability then runs `install.sh`. `flashcli upgrade` self-updates from the same release assets.

**Releases come from `main` only.** Validate `dev` by building from source (`install.sh --from-source --branch dev`, or `build_go.sh` + install the binary) — do **not** cut intermediate releases from `dev`. `release_go.sh` targets `main` (`FLASHCLI_RELEASE_TARGET` overrides). Full checklist: [CONTRIBUTING.md](CONTRIBUTING.md) → Releases.

## Tests
```bash
pytest tests/            # protocol/infer + conformance; tests/bench excluded via pyproject addopts
pytest tests/bench/      # bench helper tests (scripts/bench_*.py)
cd go && go build ./... && go test ./...   # gofmt is the formatter; run `gofmt -w .`
bash scripts/verify_cache.sh   # cache-key parity / cache-hit smoke (remote+local, GPU-free)
```
Cache-key derivation is covered by `go/internal/weights/bundle_test.go` (remote repo-name / local id / source+revision) and `go/internal/runtime/runtime_test.go` (symlink canonicalization) — keep these in sync with the `flashcli-bundle` protocol. `verify_cache.sh` is the integration counterpart (needs pulled bundles; missing prereqs SKIP).
Python tests only cover `flashcli_bundle` (protocol/infer) + conformance now; install editable first. There is **no** Python lint/typecheck/formatter/CI config — do not invent commands.

`tests/conformance/` is the language-agnostic execution-ABI gate (`docs/bundle_execution_abi.md`): fixtures for `python` / `native-exec` / `native-abi`. It runs Go via `FLASHCLI_GO_BIN` or a fresh `go build`; skips when Go is unavailable.

**Parity gates:**
- `tests/conformance/test_command_parity.py` — the Go command tree must cover the expected surface (`PYTHON_COMMANDS` = the historical contract checklist) and list Go-only commands in `GO_ONLY_COMMANDS`.
- `tests/conformance/test_go_parity.py` — execution-ABI validation agreement across fixtures.

## Architecture invariants
- Protocol `flashcli-bundle` keeps `dependencies = []` — no fastapi/uvicorn/torch/`huggingface_hub` there.
- The Go host never imports Python infer code; it re-execs `python -m flashcli_bundle.infer` (or drives a native backend). Never prepend host site-packages/PYTHONPATH.
- Bundle venvs get `flashcli-bundle[infer]` + manifest `python_dependencies` only; resolution source is `FLASHCLI_BUNDLE_PIP_SPEC` / local `flashcli-bundle/` / `FLASHCLI_INSTALL_REPO`+`REF` (see `go/internal/venv/spec.go`).
- Bundle venvs are created/installed with **uv** by default (`go/internal/uv`, `venv.SelectInstaller`). uv is **not shipped**: it is resolved from `FLASHCLI_UV_BIN`/PATH/provisioned, else downloaded from the PyPI index (sha256) with a GitHub release fallback into `~/.flashcli/tools/uv/<version>/`. `UV_CACHE_DIR` defaults under `$FLASHCLI_HOME/cache/uv` (same FS as `runtimes/` → hardlinks share torch/CUDA). `FLASHCLI_VENV_BACKEND=pip` is a deprecated escape hatch; native bundles need no uv.
- The host is a **generic, model-agnostic driver**: no model-specific logic (forward, preprocessing/postprocessing, modality shapes/dtypes, option→port mapping/defaults) outside the bundle. Python bundles own it in `entry`; native bundles declare it in the manifest `native` block + runtime port descriptors. Never hardcode a model's constants/shapes/preprocessing in `go/`.
- Manifest `protocol_version` must equal `flashcli_bundle.version.PROTOCOL_VERSION` (currently `1`); native kinds add `runtime_abi_version` / `exec_protocol_version` = `1`.
- **Weights: download completeness ≠ bundle readiness.** The host owns download completeness: it writes `.flashcli_download.json` (expected remote `path`+`size`) **before** transferring, keeps it on failure (resume), and marks in-progress downloads with `.flashcli_download.incomplete`; `pull` re-lists. The bundle owns readiness via `flashcli-bundle.json` (`allow_patterns`/`require_any_patterns`/`require_norm_stats`). Never encode model-specific filenames in `go/`.
- **Offline guarantee:** `run`/`serve` are local-first — a complete manifest or a legacy cache (no manifest, no incomplete marker) that satisfies bundle readiness is accepted **without network**; network is used only when artifacts are missing, on an explicit `flashcli pull` (forces remote verification), or for a protocol `CACHE_SCHEMA_VERSION` upgrade. Once preparation succeeds, later runs must work offline. A present-but-incomplete manifest is never accepted; an interrupted download resumes from the recorded expected set.

Details: `docs/module_layers.md`, `docs/architecture.md`, `docs/bundle_execution_abi.md`.

## Working with bundles
- Ref syntax: FlashHub `flashcli-bundle/<name>:<version>` or local `bundles/<name>` (dir must contain `flashcli-bundle.json`). v4 bundles are one model / one implementation; split models into separate bundles.
- Local dev build (needs a FlashRT clone), then run:
  ```bash
  bash bundles/qwen3_8b_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
  flashcli serve bundles/qwen3_8b_nvfp4 --port 8000
  # Qwen3.6-27B is a separate bundle: bundles/qwen36_27b_nvfp4
  ```
- Release: `bash scripts/release_bundle.sh --bundle <name> --clean` (current host env) or `cd bundles/<name> && bash release.sh --clean`; full Docker/multi-CUDA matrix is opt-in with `--matrix`. Validate with `flashcli bundle validate bundles/<name>`.
- Long builds/serves: `bash scripts/run_bg.sh --name JOB -- <cmd>`, then `--status` / `--tail` / `--wait` / `--stop` (logs under `logs/`).
- Weights are never stored in the bundle; the tree is shared at `~/.flashcli/bundles/<name>/<version>/` and v4 weights live in the shared store `~/.flashcli/models/store/<source>/<repo>@<revision>-<hash>/` (extra weights under `extra/<key>/`).

## Conventions
- Code, shell, and JSON/YAML comments in **English**; user docs English with a **`*.zh-CN.md` mirror kept in sync in the same change**.
- **Docs**: see [CONTRIBUTING.md](CONTRIBUTING.md) → Documentation. Keep docs clear, concise, accurate, complete; one concept per doc, no duplication; **delete/fix outdated content**; update the authoritative spec + bundle README/BUILD + `environment.md` when behavior changes.
- **Release notes**: follow [CONTRIBUTING.md](CONTRIBUTING.md) → Release notes standard (one-line overview + **Features/Fixes** + Assets+sha256 + Full Changelog; no extra sections) on **both** GitHub and Gitee; host releases are **incremental** (keep previous releases/tags).
- **Git / commits**: see [CONTRIBUTING.md](CONTRIBUTING.md) → Git workflow. In short: branch off `dev`, PR into `dev`; Conventional Commits, **one logical change per commit**; sync `dev` → `main` via squash-and-record; never force-push `main`/`dev`.
- Do not commit secrets/tokens, `dist/`, `build/`, `.native-cache/`, `logs/`, weights, or FlashRT source.
- `bundles/<name>/README.md` is user-facing (FlashHub); `BUILD.md` is maintainer-facing.
- Do not commit FlashRT source into this repo; it is a sibling clone used only as build input.
- Version is single-sourced from root `pyproject.toml [project].version`; `scripts/build_go.sh` injects it into the Go binary via `-ldflags`.
