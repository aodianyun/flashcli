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
├── flashcli-bundle/        # Bundle protocol + infer package (flashcli_bundle)
├── go/                     # Host CLI (Go binary; no model forward passes)
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
./install.sh --from-source          # build+install the Go host (or: bash scripts/build_go.sh)
pip install -e "./flashcli-bundle"   # protocol (for pytest)
# To run infer module tests locally:
pip install -e "./flashcli-bundle[infer]"
flashcli doctor
```

Run tests:

```bash
pytest tests/              # unit/integration (default; excludes tests/bench)
pytest tests/bench/        # bench script helpers (scripts/bench_*.py)
pytest tests/ tests/bench/ # full suite including bench
```

## Git workflow

### Branches

| Branch | Purpose |
|--------|---------|
| `main` | Stable / release branch (default). Only validated changes land here. |
| `dev` | Integration + validation branch. Day-to-day work and testing land here; synced to `main` after validation. |
| `feat/<topic>`, `fix/<topic>` | Short-lived work branches off `dev`; PR back into `dev`. |

Rules:

- Branch work off `dev`; open PRs **into `dev`**. `main` is updated from `dev` only after validation.
- Sync `dev` → `main` as a **fast-forward** when possible (`git push origin dev:main`); otherwise via a reviewed merge PR.
- **Never rewrite pushed history** — no force-push to `main`/`dev`; fix forward with new commits.
- Rebase your branch on `dev` before merging; resolve conflicts locally (do not merge `main` into a feature branch just to update it).

### Commit messages (Conventional Commits)

```
type(scope): imperative summary
```

- **type** ∈ `feat | fix | refactor | perf | docs | test | build | ci | chore`.
- **scope** is optional but preferred: `host`, `install`, `weights`, `venv`, `manifest`, `native`, `cli`, `flashhub`, `bundle`, `docs`, `go`, `python`.
- **summary**: imperative mood ("add", not "added"), ≤ ~72 chars, no trailing period.
- **body** (optional): *why* + notable changes, wrapped at ~72 cols.
- **breaking changes**: add a `BREAKING CHANGE:` footer describing the impact.
- **issue refs**: add `Refs: #123` / `Closes: #123` in the footer.

Rules:

- **One logical change per commit.** Don't mix unrelated code, refactors, and docs. A pure docs change is `docs: …` (or `docs(scope): …`); a bug fix is `fix(…)` even when it also touches a doc.
- Don't mix pure formatting/renames with behavior changes in one commit.
- Don't commit secrets/tokens, `dist/`, `build/`, `.native-cache/`, `logs/`, model weights, or FlashRT source.
- Keep subjects/bodies in **English** (see Language policy).

Examples:

```
feat(install): add --branch alias for --ref (default main)
fix(cuda): use host loader before pip-installing CUDA userland
docs(environment): document only variables the Go host reads
refactor(weights): share cache-key resolution between pull and run
```

### Merging

- PRs target `dev` and must pass `go test ./...`, `pytest tests/` (protocol/infer + conformance), and `gofmt -w .` clean.
- Prefer **squash merge** for a feature branch (one logical commit) or **rebase** for a clean linear history; avoid merge-commit noise.
- After validation, sync `dev` → `main` (fast-forward preferred). Do not push directly to `main` for routine work.

### Releases

- **Host (Go)**: bump `[project].version` in `pyproject.toml`, commit (`chore(release): bump version to X`), tag `vX` on the release commit, then `bash scripts/release_go.sh --upload` (GitHub) and upload the same assets to Gitee.
- **Bundles**: follow the maintainer checklist below and [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md).

## Pull request guidelines

1. **Scope** — Keep changes in `flashcli/`. Do not commit FlashRT source changes inside flashcli PRs.
2. **No inference in CLI** — Do not add model-specific forward logic under `go/`. Use bundle `entry` modules.
3. **Host CLI vs bundle venv (invariants)** — See [docs/architecture.md](docs/architecture.md#host-cli-vs-bundle-infer-important).

   | Allowed in bundle venv | Host only (never bundle venv) |
   |--------------------------|-----------------------------------------------------------|
   | ``flashcli-bundle[infer]`` | ``flashcli`` (Go binary — never pip) |
   | ``python_dependencies`` from manifest (torch, transformers, …) | weight download / Hub clients (Go) |

   Bundle re-exec runs ``python -m flashcli_bundle.infer`` inside the bundle venv. Tests: ``tests/conformance/``. **Do not** prepend host ``site-packages`` or pip-install ``flashcli`` into bundle venvs.

4. **Preset refs** — Upload to [FlashHub](https://flashhub.top); document the ref in the bundle README (and BUILD for maintainers). No bundled catalog file.
5. **Docs** — Update English docs when behavior or release workflow changes. Mirror important changes in `*.zh-CN.md` when applicable.
6. **Comments** — New code comments and script headers in English.
7. **Commits** — Follow the [Git workflow](#git-workflow) section: Conventional Commits (`type(scope): imperative`), **one logical change per commit**, no pushed-history rewrites.

## Adding a new bundle / preset ref

1. Copy structure from `bundles/pi05_libero/`, `bundles/qwen_nvfp4/`, `bundles/groot_n16/` (script entry + `extra_weights`), or `bundles/groot_n17/` (script entry, N1.7 `set_prompt` + `infer`, no `extra_weights`).
2. Add `flashcli-bundle.json` (format_version 3, **protocol_version 1**), `entry` modules, `release-matrix.env`, `_bundle_build.sh`.
3. Declare bundle CLI flags in manifest **`run_options`** / **`serve_options`**. Entry modules import protocol/helpers from **`flashcli_bundle`** (installed via git `flashcli-bundle` subdirectory or `pip install -e ./flashcli-bundle`), not from the full `flashcli` CLI package.
4. Follow [docs/bundle_publish_standard.md](docs/bundle_publish_standard.md) (manifest / entry spec).
5. Build on **Linux + NVIDIA GPU** (see release checklist below).
6. `flashcli bundle validate bundles/<name>`
7. Smoke-test `flashcli run <ref> --help`, `flashcli run` / `flashcli serve` as applicable.
8. Upload to [FlashHub](https://flashhub.top); document ref (e.g. `flashcli-bundle/my_model:1.0.0` or `@variant` for multi-model repos).
9. Update bundle README / BUILD (and README supported-examples table if applicable).

## Release bundle checklist (maintainers)

**Full steps:** [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) (English summary) · [docs/bundle_builder_guide.zh-CN.md](docs/bundle_builder_guide.zh-CN.md) (complete, 中文) · matrix reference [docs/runtime-matrix.md](docs/runtime-matrix.md).

After uploading `dist/` to FlashHub:

- [ ] `bash scripts/release_bundle.sh --bundle <name> --clean` → upload `dist/` to FlashHub
- [ ] `flashcli bundle validate bundles/<name>` and smoke `run` / `serve` on target GPU
- [ ] Document ref strings in README / BUILD (Qwen: same repo, different `@variant`)

Matrix constraints: pi05 **SM89 + SM120** (cu124 on SM89; cu130 on both); qwen / qwen3_vl / groot_n16 **cu130 / SM120 / py312**; **groot_n17** **cu130 / SM120 / py310** (Isaac-GR00T) — see runtime-matrix doc.

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models envs <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
