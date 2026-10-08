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
bash scripts/release_go.sh [--upload]  # build, optionally publish via `gh`
```
`install.sh` installs the `flashcli` binary (default: latest release assets + sha256; `--from-source` builds with Go) and writes `~/.flashcli/install.env` (bundle venv source: local checkout or repo/ref). Missing OS tools are auto-installed via the package manager. `auto_install.sh` picks GitHub/Gitee by reachability then runs `install.sh`. `flashcli upgrade` self-updates from the same release assets.

## Tests
```bash
pytest tests/            # protocol/infer + conformance; tests/bench excluded via pyproject addopts
pytest tests/bench/      # bench helper tests (scripts/bench_*.py)
cd go && go build ./... && go test ./...   # gofmt is the formatter; run `gofmt -w .`
```
Python tests only cover `flashcli_bundle` (protocol/infer) + conformance now; install editable first. There is **no** Python lint/typecheck/formatter/CI config — do not invent commands.

`tests/conformance/` is the language-agnostic execution-ABI gate (`docs/bundle_execution_abi.md`): fixtures for `python` / `native-exec` / `native-abi`. It runs Go via `FLASHCLI_GO_BIN` or a fresh `go build`; skips when Go is unavailable.

**Parity gates:**
- `tests/conformance/test_command_parity.py` — the Go command tree must cover the expected surface (`PYTHON_COMMANDS` = the historical contract checklist) and list Go-only commands in `GO_ONLY_COMMANDS`.
- `tests/conformance/test_go_parity.py` — execution-ABI validation agreement across fixtures.

## Architecture invariants
- Protocol `flashcli-bundle` keeps `dependencies = []` — no fastapi/uvicorn/torch/`huggingface_hub` there.
- The Go host never imports Python infer code; it re-execs `python -m flashcli_bundle.infer` (or drives a native backend). Never prepend host site-packages/PYTHONPATH.
- Bundle venvs get `flashcli-bundle[infer]` + manifest `python_dependencies` only; resolution source is `FLASHCLI_BUNDLE_PIP_SPEC` / local `flashcli-bundle/` / `FLASHCLI_INSTALL_REPO`+`REF` (see `go/internal/venv/spec.go`).
- No model-specific forward logic outside bundle `entry`.
- Manifest `protocol_version` must equal `flashcli_bundle.version.PROTOCOL_VERSION` (currently `1`); native kinds add `runtime_abi_version` / `exec_protocol_version` = `1`.

Details: `docs/module_layers.md`, `docs/architecture.md`, `docs/bundle_execution_abi.md`.

## Working with bundles
- Ref syntax: FlashHub `flashcli-bundle/<name>:<version>[@variant]` or local `bundles/<name>[@variant]` (dir must contain `flashcli-bundle.json`). Multi-variant bundles (e.g. `qwen_nvfp4`) require `@variant`.
- Local dev build (needs a FlashRT clone), then run:
  ```bash
  bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
  flashcli serve bundles/qwen_nvfp4@qwen36 --port 8000 --K 6
  ```
- Release: `bash scripts/release_bundle.sh --bundle <name> --clean` (Docker cu124/cu130 matrix) or `cd bundles/<name> && bash release.sh --clean`; validate with `flashcli bundle validate bundles/<name>`.
- Long builds/serves: `bash scripts/run_bg.sh --name JOB -- <cmd>`, then `--status` / `--tail` / `--wait` / `--stop` (logs under `logs/`).
- Weights are never stored in the bundle; cached under `~/.flashcli/models/<bundle>/<version>@<variant>/`.

## Conventions
- Code, shell, and JSON/YAML comments in **English**; user docs English with optional `*.zh-CN.md` mirrors — update the zh-CN copy when behavior docs change.
- `bundles/<name>/README.md` is user-facing (FlashHub); `BUILD.md` is maintainer-facing.
- Do not commit FlashRT source into this repo; it is a sibling clone used only as build input.
- Version is single-sourced from root `pyproject.toml [project].version`; `scripts/build_go.sh` injects it into the Go binary via `-ldflags`.
- `build/` and `.native-cache/` are build artifacts (gitignored).
