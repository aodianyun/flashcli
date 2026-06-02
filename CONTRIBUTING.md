# Contributing to flashcli

Thank you for contributing. This project is intended for open source on GitHub. The audience includes third-party integrators, bundle authors, and maintainers.

**Language policy**

| Location | Language |
|----------|----------|
| Code, shell scripts, YAML/JSON comments | **English** |
| User-facing docs (`README.md`, `docs/*.md`, `bundles/*/README.md`, …) | **English** (with optional `*.zh-CN.md` translations) |
| Explicit Chinese docs (`*.zh-CN.md`, `docs/*zh-CN*`) | 简体中文 |

## Repository layout

```text
flashcli/
├── src/flashcli/           # CLI, catalog, bundle loader (no model forward passes)
├── bundles/                  # Model bundle sources + release-matrix.env
├── scripts/                  # Shared release pipeline
└── docs/                     # Public documentation

FlashRT/                      # Sibling clone — inference kernels (build input only)
```

flashcli **distributes and loads** Model Bundles; inference lives in bundle `entry` modules and FlashRT.

See [docs/runtime-matrix.md](docs/runtime-matrix.md) and [docs/model_bundle_standard.md](docs/model_bundle_standard.md) for bundle format and release workflow.

## Development setup

```bash
cd flashcli
pip install -e ".[dev]"   # or: pip install -e .
flashcli doctor
flashcli models list
```

Run tests:

```bash
pytest tests/
```

## Pull request guidelines

1. **Scope** — Keep changes in `flashcli/`. Do not commit FlashRT source changes inside flashcli PRs.
2. **No inference in CLI** — Do not add model-specific forward logic under `src/flashcli/`. Use bundle `entry` modules.
3. **Catalog** — Edit `src/flashcli/catalog/models.yaml` only after a bundle is built and validated on real hardware.
4. **Docs** — Update English docs when behavior or release workflow changes. Mirror important changes in `*.zh-CN.md` when applicable.
5. **Comments** — New code comments and script headers in English.
6. **Commits** — Clear, imperative subject lines; one logical change per commit when possible.

## Adding a new catalog preset / bundle

1. Copy structure from `bundles/pi05_libero/` or `bundles/qwen_nvfp4/`.
2. Add `flashcli-bundle.json`, `entry` modules, `release-matrix.env`, `_bundle_build.sh`.
3. Follow [docs/model_bundle_standard.md](docs/model_bundle_standard.md).
4. Build on **Linux + NVIDIA GPU** (see release checklist below).
5. `flashcli bundle validate bundles/<name>`
6. Smoke-test `flashcli run` / `flashcli serve` as applicable.
7. Add preset to `models.yaml` with `bundle.zip`, `path`, or `git`.
8. Update [README.md](README.md) and bundle README.

## Release bundle checklist (maintainers)

Use this before uploading a new runtime zip to CDN and updating `models.yaml`.

### Prerequisites

- Linux x86_64 host with Docker + NVIDIA GPU (or `--native` with correct CUDA toolkits on host)
- Sufficient disk for matrix builds and Docker images
- Workspace layout:

```text
workspace/
├── flashcli/
└── FlashRT/          # auto-cloned by release_bundle.sh if missing
```

### Build

```bash
cd flashcli

# Pi0.5 — sm89 × cu124 + cu130 × py310/311/312
bash scripts/release_bundle.sh --bundle pi05_libero --clean

# Qwen NVFP4 — sm120 × cu130 only × py310/311/312
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

Optional background run with log:

```bash
bash scripts/run_bg.sh --name release-pi05 -- \
  bash scripts/release_bundle.sh --bundle pi05_libero --clean
bash scripts/run_bg.sh --name release-pi05 --tail
```

Expected artifact name pattern:

```text
flashcli-bundle-{name}-{FlashRT_ABI}-sm{SM}-multi-linux-x86_64-{YYYYMMDD-HHMMSS}.zip
```

Details: [docs/runtime-matrix.md](docs/runtime-matrix.md).

### Validate before publish

- [ ] `flashcli bundle validate bundles/<name>` passes (matrix + ABI probe)
- [ ] `lib/` contains all cells declared in `release-matrix.env`
- [ ] Zip includes runtime files only (no `build.sh`, README, or dev artifacts — see `RELEASE_PACK_FILES`)
- [ ] `flashcli models envs <preset>` matches expected host keys on target GPUs
- [ ] Smoke `flashcli run` / `flashcli serve` on at least one matrix cell (e.g. pi05 SM89+cu124, qwen SM120+cu130)
- [ ] Upload zip to CDN; update `models.yaml` `bundle.zip` URL(s)
- [ ] For qwen: both `qwen3-8b-nvfp4` and `qwen36-27b-nvfp4` share the **same** zip URL

### Known matrix constraints

| Bundle | Note |
|--------|------|
| `pi05_libero` | **SM89 only.** cu124 line: FA2 is sm_89 AOT. cu130 line: FA2 multi-arch; kernels sm_89. |
| `qwen_nvfp4` | **No cu124 line** — SM120/NVFP4 requires nvcc ≥ 12.8 (use `25.10-py3` container). |

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models envs <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
