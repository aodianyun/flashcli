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
├── desktop/                # egui/eframe desktop client + Windows installer source
├── installer/windows/      # Inno Setup installer source
├── bundles/                  # Model bundle sources + release-matrix.env
├── scripts/                  # Shared release pipeline
└── docs/                     # User-facing documentation (maintainer docs: see CONTRIBUTING)

FlashRT/                      # Sibling clone — inference kernels (build input only)
```

flashcli **distributes and loads** Model Bundles; inference lives in bundle `entry` modules and FlashRT.

**Maintainers:** build/release workflow → [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md) · [docs/runtime-matrix.md](docs/runtime-matrix.md). Full index: [docs/README.md](docs/README.md).

## Workflow at a glance

| Phase | Steps |
|---|---|
| **Develop** | Branch off `dev` → code → tier 1 (`go test ./...`, `pytest tests/`, `gofmt -l .`) → apply the contract checklist → PR into `dev`. |
| **Integrate** | Review → tier 2 (`verify_e2e.sh`) → rebase/squash into `dev`; run tier 2h (`--heavy`) before `main` or a release candidate. |
| **Release** | Bump versions on `dev` → sync `dev` → `main` (maintainer approval) → live index check → tier 3 gate (`--heavy --network`) → Windows installer → release notes → `release_go.sh --upload` → `verify_release.sh`. |

Branch exception: local-only, unpushed maintenance explicitly requested by the
maintainer may be committed directly on `dev`. Shared work uses a feature branch
and a PR.

Details: [development_verification_standard.md](docs/development_verification_standard.md) · [release_verification_standard.md](docs/release_verification_standard.md) · [Git workflow](#git-workflow).

## Development setup

```bash
cd flashcli
./install.sh --from-source          # build+install the Go host
bash scripts/build_dev_bins.sh      # local test binaries (see "Test binaries")
pip install -e "./flashcli-bundle"   # protocol (for pytest)
# To run infer module and HTTP protocol tests locally (pytest/httpx/numpy):
pip install -e "./flashcli-bundle[infer,test]"
flashcli doctor
```

Verification has two authoritative process documents:

- [development_verification_standard.md](docs/development_verification_standard.md) — tiers 1/2/2h, test binaries, contract checks, PR definition of done.
- [release_verification_standard.md](docs/release_verification_standard.md) — tier 3 gate, versioning, release sequence, artifacts, notes, post-release checks.

Quick commands:

```bash
bash scripts/build_dev_bins.sh          # only the two test binaries
bash scripts/verify_e2e.sh              # tier 2 (Linux/WSL)
bash scripts/verify_e2e.sh --heavy      # tier 2h (before main / RC)
bash scripts/verify_e2e.sh --heavy --network  # tier 3 (release only)
```

`scripts/build_go.sh` is **release-only** (Linux amd64/arm64 + Windows setup);
do not use it just to run tests. Acceptance refuses `dist/go` binaries older than
`go/` sources.

### Binaries and the desktop client

Release artifacts, naming, and the publish sequence are defined in
[release_verification_standard.md](docs/release_verification_standard.md) §6.
Local tests use `scripts/build_dev_bins.sh`; release assets use
`scripts/build_go.sh`.

The desktop client lives in `desktop/` (Rust, egui/eframe) and only uses the
daemon's HTTP API; see [desktop/README.md](desktop/README.md). Build the Windows
package (client + Go assets + Inno Setup, requires Rust MSVC and Inno Setup 6):

```bash
powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1
# reuse already-built Go assets: add -SkipGo
```

Layout: `go/cmd/{flashcli,flashserver,flashserver-setup}` (entrypoints),
`go/internal/server` (daemon API + embedded console), `go/internal/setup`
(installers), `installer/windows/` (Inno Setup script).

### Shared host code (CLI + flashserver)

`flashcli` and `flashserver` are frontends over the same cache. Cache discovery, weights key/readiness, runtime IDs/paths, disk accounting, ref-path resolution, and cleanup **must** live in `go/internal/host` and be reused by both.

- Do **not** add a second marker walker, weights-readiness check, directory-size walker, or cleanup path resolver under `go/internal/cli` or `go/internal/server`.
- Implement new behavior in `host`, then call it from both frontends. Keep only presentation (flags, tables, prompts, HTTP handlers) in the frontend.
- Add/extend tests in `go/internal/host` and the relevant CLI command tests (`du`, `models list`, `bundle clean`). `go test ./...` must pass.
- `flashcli cache clean` removes only the shared cache group (downloads, base Python, uv) and matches `/v1/storage/clean {"targets":["cache"]}`. Model bundles/weights/runtimes belong to `flashcli bundle clean` / `/v1/models/clean`; shared weights/runtime stay while another cached ref references them.

Architecture rule: [docs/architecture.md](docs/architecture.md) → Shared host services; placement checklist: [docs/module_layers.md](docs/module_layers.md).

## Git workflow

### Branches

| Branch | Purpose |
|--------|---------|
| `main` | Stable / release branch (default). Only validated changes land here. |
| `dev` | Integration + validation branch. Day-to-day work and testing land here; synced to `main` after validation. |
| `feat/<topic>`, `fix/<topic>` | Short-lived work branches off `dev`; PR back into `dev`. |

Rules:

- Branch work off `dev`; open PRs **into `dev`**. `main` is updated from `dev` only after validation.
- Sync `dev` → `main` (**squash-and-record**). **Do not run this sync or push
  `main` without explicit maintainer approval.** Prepare the squash locally,
  show the pending features/commits and the proposed subject/body, and wait for
  confirmation. The squash commit **must carry a body summarizing the
  user-visible changes since the previous sync**; do not leave only a
  `chore(sync)` subject:

  ```bash
  # main: collapse dev into a single commit (keeps main linear)
  git switch main && git pull origin main
  git merge --squash dev
  git commit -F - <<'MSG'
  chore(sync): desktop navigation + app categories (1.0.9.20261120)

  Features:
  - desktop: sidebar order is Applications, Models, Status, Logs, Settings
  - desktop: application category chips use a fixed order

  Fixes:
  - desktop: category chips no longer follow the FlashHub list order
  MSG
  git push origin main

  # dev: record the squash so future syncs don't replay changes / re-conflict
  git switch dev
  git merge -s ours main -m "chore: record squash merge from main (ours)"
  git push origin dev
  ```

  - `main` gains exactly **one** commit per sync and stays linear; `dev` keeps its granular history.
  - The **subject** must contain a short user-visible summary (GitHub/Gitee list
    views show only the subject); put the detailed Features/Fixes in the body.
    Do not use a bare `chore(sync): merge dev into main`.
  - The commit body is the audit trail for `main`: group the user-visible
    Features/Fixes since the previous sync (release notes are a good source);
    never list raw commit hashes or internal refactors.
  - `dev` individual commit messages are **not** carried into `main` (they remain on `dev`) — this is the accepted trade-off of the squash flow, which is why the body is required.
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
- Feature branch → `dev`: choose by commit quality.
  - **Rebase (default)** when the branch is already a series of logical Conventional Commits: `git rebase dev` on the branch, then fast-forward `dev` (or GitHub "Rebase and merge"). Authorship and messages are preserved, history stays linear, and the branch can be deleted afterwards without losing anything.
  - **Squash** when the branch is exploratory (WIP/fixup commits, repeated rewrites of the same code): `dev` then gets one commit that summarizes the change.
  - Do **not** create `--no-ff` merge commits on `dev` (no merge bubbles). Rebase the feature branch onto `dev` instead of merging `dev` into it, and re-push with `--force-with-lease`.
  - Do not force-push `dev` once it is shared; replace a commit you just pushed by mistake only with `--force-with-lease`.
- `dev` → `main`: **squash-and-record** (see above) — `main` gets one linear squash commit per sync, and `dev` records it with `git merge -s ours main`. Do not `--no-ff` merge or rely on fast-forward, and do not push directly to `main` for routine work.
- Squash commit summary: `chore(sync): squash merge dev into main` (or a concise `type(scope): …` describing the release).

### Contract changes

Before committing, follow the change-impact table in
[development_verification_standard.md](docs/development_verification_standard.md#4-contract-checks-by-change-type).
Every HTTP/API change updates the single OpenAPI contract, the API index, the
console reference, the desktop caller, and the zh-CN mirror in the same change.

### Releases

Release verification and publishing are defined in
[release_verification_standard.md](docs/release_verification_standard.md).

- Releases are cut from **`main`** only; never publish an intermediate release
  from `dev`.
- Host releases are incremental: keep every published release and tag.
- `release_go.sh --upload` refuses without a full `--heavy --network` gate for
  the exact commit being published.
- Release notes follow
  [release_verification_standard.md §5](docs/release_verification_standard.md#5-release-notes-standard).

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
5. **Docs** — Update English docs when behavior or release workflow changes. Mirror important changes in `*.zh-CN.md` when applicable. Verification is defined by [development_verification_standard.md](docs/development_verification_standard.md) and [release_verification_standard.md](docs/release_verification_standard.md); do not duplicate their tiers or checklists elsewhere.
6. **Comments** — New code comments and script headers in English.
7. **Commits** — Follow the [Git workflow](#git-workflow) section: Conventional Commits (`type(scope): imperative`), **one logical change per commit**, no pushed-history rewrites.
8. **flashserver gateway/scheduler** — Follow [docs/flashserver_gateway_scheduler_spec.md](docs/flashserver_gateway_scheduler_spec.md) and [docs/plans/flashserver_gateway_scheduler_plan.md](docs/plans/flashserver_gateway_scheduler_plan.md). `/v1/*` is the OpenAI gateway, `/api/v1/*` is management; applications and the desktop must never start/stop/load/unload models or use child endpoints. Preload/unload are disk operations, resident start/stop is scheduler-owned, and placement is host-only. Update the spec and its zh-CN mirror for every behavior change.

### Shared code (CLI + flashserver)

Any behavior needed by both `go/internal/cli` and `go/internal/server` **must be implemented once in a shared package** and called from both. Do not copy a helper, orchestration sequence, path derivation, or state predicate into a frontend "for now".

| Shared concern | Canonical implementation |
|---|---|
| Pull / runtime+venv preparation / weights | `host.Pull`, `host.EnsureRuntime`, `host.ResolveWeights` |
| Cache discovery, keys, sizes, cleanup | `host.*` |
| Serve log name / tail / readiness | `modelrun.LogName`, `modelrun.TailLines`, `modelrun.WaitHealthy` |
| App install/start/stop/state/restore predicate | `apps.Service`, `apps.WasRunning` |
| Manifest/env/variant/entry resolution | `manifest.*`, `host.ApplyEnv` |
| GPU / system probes | `gpu.*`, `preflight.*`, `host.EnsureSystemRequirements` |

Before adding code, search for an existing shared function; if the behavior is missing, add it to the shared package first. `go test ./internal/architecture/...` fails on the mechanical re-introductions (direct `nvidia-smi`, log-name `NewReplacer`, `filepath.Walk*`, `.flashcli_download.incomplete`). Full rules: [docs/architecture.md → Shared host services](docs/architecture.md#shared-host-services-cli--flashserver).

**Not shared (keep it in the frontend):** HTTP/auth/jobs/websocket, CLI flags/prompts/output formatting, Manager slot/VRAM/owner admission vs. the CLI's single-process launch, daemon restore scheduling/telemetry, desktop UI, and any other frontend-specific orchestration. The test is simple: if both sides must make the *same decision about the same on-disk state or model readiness*, share it; if it is UX, scheduling policy, or presentation, do not force it into a shared package. Adapters (Launcher/Stopper/Log hooks) may differ.

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

- **Audience first.** User-facing docs live in root `README` / `bundles/<name>/README.md`; contracts/specs in `docs/`; delivery plans in `docs/plans/`; maintainer workflows in `docs/bundle_builder_guide.md`. Keep `docs/README.md` as the index. Follow [docs/documentation_standard.md](docs/documentation_standard.md) for directories and naming (`*_spec.md`, `plans/*_plan.md`, `*_standard.md`, `*_guide.md`).
- **Process docs have one home.** Development verification is [docs/development_verification_standard.md](docs/development_verification_standard.md); release verification is [docs/release_verification_standard.md](docs/release_verification_standard.md). Link to them instead of copying their tables into CONTRIBUTING or other docs.
- **English is authoritative; keep the `*.zh-CN.md` mirror in sync** in the same change (same directory). Missing/outdated zh mirrors are a bug.
- **Delete or fix outdated content** instead of appending. Prefer editing the authoritative doc over creating a new one; avoid doc proliferation.
- **One concept, one home.** Do not duplicate a spec across docs — link to the authoritative one. A plan must not redefine behavior; the spec wins.
- **Prefer tables and small diagrams** over prose when clearer.
- **Verify relative links** after moving/renaming files (plans refer to root specs as `../<spec>.md`).
- **When behavior changes**, update together: the authoritative spec (`docs/*.md`), the affected bundle `README`/`BUILD`, and `docs/environment.md` if env vars changed.

### Architecture and flow diagrams

`docs/images/` is the only home for diagrams. A stale or inconsistent diagram is a documentation bug, not decoration.

- **Pairing and naming.** Every diagram ships as `<name>.en.svg` + `<name>.en.png` and `<name>.zh-CN.svg` + `<name>.zh-CN.png`. Both languages must show the same boxes, arrows, and labels; only the text changes. Update [docs/architecture.md](docs/architecture.md) and its zh-CN mirror in the same change.
- **Canvas and hierarchy.** 1600×900, light background (`#F7F9FC`), 48 px outer margins. Title 34 px/700 at the top left, `v1` at the top right, a 1 px divider at y=100, uppercase column labels at y=132. Use at most four columns.
- **Two layouts.** Overview/module maps use the reference card style: white group cards (16 px radius, soft shadow, `#E2E8F0` border) with a 4 px accent dot and an 18.5 px title, plus `#F8FAFC` item cards (9 px radius). Flow/detail diagrams use **swimlanes and process nodes**: light lane backgrounds, 8 px process boxes with the same 12.1 px title / 10.3 px detail text, decision diamonds, dashed stores, and orthogonal edges. Do not wrap a detailed flow in one large card or nest cards inside cards.
- **Palette.** Ink `#0F172A`, body `#475569`, muted `#94A3B8`, lines `#E2E8F0`, card `#FFFFFF`, item `#F8FAFC`. Accents: blue `#2563EB` (data/request), green `#0F766E` (local execution), amber `#B45309` (external/disk), red `#DC2626` (failure). No gradients or pastel fills.
- **Arrows.** 1.4 px straight or orthogonal lines with one semantic accent color. Labels are optional, 10.5 px muted, and must fit the gap; omit the label rather than clipping it. Do not cross cards; route around them.
- **Content.** One concept per diagram: overview, run/serve, gateway/scheduler, bundle/runtime stack, Go module map, FlashHub flow, or app lifecycle. Match the authoritative spec; do not invent routes or states. Show the gateway split (`/v1` vs `/api/v1`), scheduler ownership, and custom-path passthrough where relevant.
- **Overview vs detail.** The system overview is the only coarse view. Every other diagram is **step-level**: show inputs, decisions, branches, state transitions, error/retry paths, and the component each step touches. Do not collapse a multi-step flow into one card.
- **Flow clarity.** Use orthogonal arrows in reading order, label branches, and never route a line across a card. Use dashed lines for failure/retry paths. Every arrow must have an unambiguous source and target.
- **Source and rendering.** The SVG is authoritative; never hand-edit a PNG. Render with `rsvg-convert -w 1600 -h 900 -o docs/images/<name>.<lang>.png docs/images/<name>.<lang>.svg`. Check at 100% and 50% for clipped text, CJK glyphs, arrow labels, and both languages before committing.
- **No second source of truth.** Hand-laid SVG replaces Graphviz `.dot`; delete stale `.dot` files instead of keeping both.

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models show <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
