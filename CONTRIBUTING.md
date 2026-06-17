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
├── flashcli-bundle/        # Bundle protocol package (flashcli_bundle)
├── src/flashcli/           # CLI, preset ref, bundle loader (no model forward passes)
├── bundles/                  # Model bundle sources + release-matrix.env
├── scripts/                  # Shared release pipeline
└── docs/                     # User-facing documentation (maintainer docs: see CONTRIBUTING)

FlashRT/                      # Sibling clone — inference kernels (build input only)
```

flashcli **distributes and loads** Model Bundles; inference lives in bundle `entry` modules and FlashRT.

**Maintainers:** build/release workflow → [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) · [docs/bundle_builder_guide.zh-CN.md](docs/bundle_builder_guide.zh-CN.md) · [docs/runtime-matrix.md](docs/runtime-matrix.md) (linked from this file only).

## Development setup

```bash
cd flashcli
pip install -e "./flashcli-bundle"   # protocol (host CLI)
pip install -e ".[dev]"            # flashcli host CLI
# To run infer module tests locally:
pip install -e "./flashcli-bundle[infer]"
flashcli doctor
flashcli models list
```

Run tests:

```bash
pytest tests/              # unit/integration (default; excludes tests/bench)
pytest tests/bench/        # bench script helpers (scripts/bench_*.py)
pytest tests/ tests/bench/ # full suite including bench
```

## Pull request guidelines

1. **Scope** — Keep changes in `flashcli/`. Do not commit FlashRT source changes inside flashcli PRs.
2. **No inference in CLI** — Do not add model-specific forward logic under `src/flashcli/`. Use bundle `entry` modules.
3. **Host CLI vs bundle venv (invariants)** — See [docs/architecture.md](docs/architecture.md#host-cli-vs-bundle-infer-important).

   | Allowed in bundle venv | Host only (never bundle venv) |
   |--------------------------|-----------------------------------------------------------|
   | ``flashcli-bundle[infer]`` | ``flashcli`` CLI package (pip) |
   | ``python_dependencies`` from manifest (torch, transformers, …) | ``huggingface_hub`` (weight pull) |

   Bundle re-exec runs ``python -m flashcli_bundle.infer`` inside the bundle venv. Tests: ``test_reexec_argv.py``, ``test_flashcli_bundle_infer.py``. **Do not** prepend host ``site-packages`` or pip-install ``flashcli`` into bundle venvs.

4. **Preset refs** — Document new FlashHub refs in README / bundle QUICKSTART after upload; no bundled catalog file.
5. **Docs** — Update English docs when behavior or release workflow changes. Mirror important changes in `*.zh-CN.md` when applicable.
6. **Comments** — New code comments and script headers in English.
7. **Commits** — Clear, imperative subject lines; one logical change per commit when possible.

## Adding a new bundle / preset ref

1. Copy structure from `bundles/pi05_libero/` or `bundles/qwen_nvfp4/`.
2. Add `flashcli-bundle.json` (format_version 3, **protocol_version 1**), `entry` modules, `release-matrix.env`, `_bundle_build.sh`.
3. Declare bundle CLI flags in manifest **`run_options`** / **`serve_options`**. Entry modules import protocol/helpers from **`flashcli_bundle`** (installed via git `flashcli-bundle` subdirectory or `pip install -e ./flashcli-bundle`), not from the full `flashcli` CLI package.
4. Follow [docs/bundle_publish_standard.md](docs/bundle_publish_standard.md) (manifest / entry spec).
5. Build on **Linux + NVIDIA GPU** (see release checklist below).
6. `flashcli bundle validate bundles/<name>`
7. Smoke-test `flashcli run <ref> --help`, `flashcli run` / `flashcli serve` as applicable.
8. Upload to FlashHub; document ref (e.g. `flashcli-bundle/my_model:1.0.0` or `@variant` for multi-model repos).
9. Update [README.md](README.md) and bundle README.

## Release bundle checklist (maintainers)

**Full steps:** [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) (English summary) · [docs/bundle_builder_guide.zh-CN.md](docs/bundle_builder_guide.zh-CN.md) (complete, 中文) · matrix reference [docs/runtime-matrix.md](docs/runtime-matrix.md).

After uploading `dist/` to FlashHub:

- [ ] `bash scripts/release_bundle.sh --bundle <name> --clean` → upload `dist/` to FlashHub
- [ ] `flashcli bundle validate bundles/<name>` and smoke `run` / `serve` on target GPU
- [ ] Document ref strings in README / QUICKSTART (Qwen: same repo, different `@variant`)

Matrix constraints: pi05 **SM89 + SM120** (cu124 on SM89; cu130 on both); qwen **cu130 / SM120 only** — see runtime-matrix doc.

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models envs <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
