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

**Maintainers:** build/release workflow → [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) · [docs/runtime-matrix.md](docs/runtime-matrix.md). Full index: [docs/README.md](docs/README.md).

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
- Sync `dev` → `main` (**squash-and-record**):

  ```bash
  # main: collapse dev into a single commit (keeps main linear)
  git switch main && git pull origin main
  git merge --squash dev
  git commit -m "chore(sync): squash merge dev into main"
  git push origin main

  # dev: record the squash so future syncs don't replay changes / re-conflict
  git switch dev
  git merge -s ours main -m "chore: record squash merge from main (ours)"
  git push origin dev
  ```

  - `main` gains exactly **one** commit per sync and stays linear; `dev` keeps its granular history.
  - `dev` individual commit messages are **not** carried into `main` (they remain on `dev`) — this is the accepted trade-off of the squash flow.
  - Always do the `-s ours` record step on `dev` after squashing; otherwise the next `main`→`dev` merge replays squashed changes and conflicts.
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
- Feature branch → `dev`: prefer **squash merge** (one logical commit) or **rebase** for a clean linear history; avoid merge-commit noise.
- `dev` → `main`: **squash-and-record** (see above) — `main` gets one linear squash commit per sync, and `dev` records it with `git merge -s ours main`. Do not `--no-ff` merge or rely on fast-forward, and do not push directly to `main` for routine work.
- Squash commit summary: `chore(sync): squash merge dev into main` (or a concise `type(scope): …` describing the release).

### Releases

Releases are cut from **`main`** (stable) only. **Never publish an intermediate release
from `dev`.** Validate host changes by building from `dev` locally — `bash install.sh
--from-source --branch dev`, or `bash scripts/build_go.sh` + install the binary. Note
`install.sh --branch dev` **without** `--from-source` still installs the latest
*published* release, so it does **not** exercise dev host code.

Host releases are **incremental**: keep every published release and tag; remove only
unpublished test/draft releases.

**Host (Go) release checklist:**

1. Bump `[project].version` in `pyproject.toml` on `dev`; commit (`chore(release): bump version to X`).
2. Sync `dev` → `main` (squash-and-record, above) so `main` carries the validated commit.
3. Tag `vX` on the `main` release commit; push the tag.
4. `bash scripts/release_go.sh --upload` builds and publishes both GitHub and Gitee
   (target branch defaults to `main`; override with `FLASHCLI_RELEASE_TARGET`).
5. Write the release notes per the standard below on **both** platforms.
6. Verify the published assets in a clean environment:
   `bash scripts/verify_release.sh --version X` (isolated prefix; add `--mirror` for Gitee).

- **Bundles**: follow the maintainer checklist below and [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md).

#### Release notes standard

Concise; **Features** and **Fixes** only. Bold the key terms. Same text on GitHub and Gitee; host releases are **incremental** (keep previous releases/tags).

```markdown
# flashcli <version>

<one-line overview; bold the headline>

## Features
- **<area>**: <what changed, user-visible>

## Fixes
- **<area>**: <what was broken → fixed>

## Assets
- `flashcli-linux-amd64` sha256 `<…>`
- `flashcli-linux-arm64` sha256 `<…>`

**Full Changelog**: <compare or commits link>
```

Rules: short bullets, no raw commit dump, no extra sections; English (an optional one-line `> 简体中文` is fine); include asset sha256.

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

1. Copy structure from `bundles/pi05_libero/`, `bundles/groot_n16/`, `bundles/groot_n17/`, or `bundles/higgs_audio/`.
2. Add a v4 `flashcli-bundle.json` (`format_version: 4`, **protocol_version 1**) with `defaults` + `environments`, entry modules, `release-matrix.env`, `_bundle_build.sh`.
3. Declare bundle CLI flags in manifest **`run_options`** / **`serve_options`**. Entry modules import protocol/helpers from **`flashcli_bundle`** (installed via git `flashcli-bundle` subdirectory or `pip install -e ./flashcli-bundle`), not from the full `flashcli` CLI package.
4. Follow [docs/bundle_publish_standard.md](docs/bundle_publish_standard.md) (manifest / entry spec).
5. Build on **Linux + NVIDIA GPU** (see release checklist below).
6. `flashcli bundle validate bundles/<name>`
7. Smoke-test `flashcli run <ref> --help`, `flashcli run` / `flashcli serve` as applicable.
8. Upload to [FlashHub](https://flashhub.top); document the ref (e.g. `flashcli-bundle/my_model:1.0.0`).
9. Update bundle README / BUILD (and README supported-examples table if applicable).

## Release bundle checklist (maintainers)

**Full steps:** [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) (English, complete) · [docs/bundle_builder_guide.zh-CN.md](docs/bundle_builder_guide.zh-CN.md) (中文) · matrix reference [docs/runtime-matrix.md](docs/runtime-matrix.md).

After uploading `dist/` to FlashHub:

- [ ] `bash scripts/release_bundle.sh --bundle <name> --clean` → upload `dist/` to FlashHub
- [ ] `flashcli bundle validate bundles/<name>` and smoke `run` / `serve` on target GPU
- [ ] Document the v4 ref string in README / BUILD

Matrix constraints: v4 bundles declare supported environments in `flashcli-bundle.json`; see the bundle BUILD docs and runtime-matrix reference.

## Documentation

Docs are part of the product and this is a **public repository** — treat them as code. Every doc must be **clear, concise, accurate, and complete**: no verbosity, no redundancy, no stale content.

- **Audience first.** User-facing docs live in root `README` / `bundles/<name>/README.md`; contracts/specs in `docs/`; maintainer workflows in `docs/bundle_builder_guide.md`. Keep `docs/README.md` as the index.
- **English is authoritative; keep the `*.zh-CN.md` mirror in sync** in the same change. Missing/outdated zh mirrors are a bug.
- **Delete or fix outdated content** instead of appending. Prefer editing the authoritative doc over creating a new one; avoid doc proliferation.
- **One concept, one home.** Do not duplicate a spec across docs — link to the authoritative one.
- **Prefer tables and small diagrams** over prose when clearer.
- **Verify relative links** after moving/renaming files.
- **When behavior changes**, update together: the authoritative spec (`docs/*.md`), the affected bundle `README`/`BUILD`, and `docs/environment.md` if env vars changed.

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models show <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
