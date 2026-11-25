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

## Development setup

```bash
cd flashcli
./install.sh --from-source          # build+install the Go host (or: bash scripts/build_go.sh)
pip install -e "./flashcli-bundle"   # protocol (for pytest)
# To run infer module and HTTP protocol tests locally (pytest/httpx/numpy):
pip install -e "./flashcli-bundle[infer,test]"
flashcli doctor
```

Run tests in tiers — do not run the heavy tier for every edit:

| Tier | Command | When |
|------|---------|------|
| **1 — code** (default) | `cd go && go test ./...` · `pytest tests/` · `gofmt -l .` | Every change / PR |
| **2 — acceptance** (local, offline) | `bash scripts/verify_e2e.sh --heavy` | Before merging to `main`, before a release candidate |
| **3 — full release gate** (network) | `bash scripts/verify_e2e.sh --heavy --network` | Required before publishing; writes `dist/e2e-pass.json` |

Tier 1 is unit/integration with fixtures. Tier 2 runs the **real binaries**:
`flashcli version/doctor/bundle validate/models show`, real `run` on v3 and v4
Python bundles plus a native bundle, an offline FlashHub sync through a local
HTTP index (both CDN layouts), and a real `flashserver` daemon exercising
`load → endpoint → logs → unload` over HTTP. Tier 3 adds the live FlashHub
manifest check (`FLASHCLI_ACCEPTANCE_NETWORK=1`).

**Publishing is gated on the full run.** `scripts/release_go.sh --upload`
refuses to publish unless `dist/e2e-pass.json` records a `--heavy --network`
pass for the exact commit being released (`FLASHCLI_SKIP_E2E_GATE=1` exists only
for pipeline tests). Do not tag or replace release assets before that run is
green.

```bash
pytest tests/              # tier 1 (excludes tests/bench)
pytest tests/bench/        # bench script helpers (scripts/bench_*.py)
bash scripts/verify_e2e.sh # tier 2 (Linux/WSL; builds dist/go)
```

### Binaries and the desktop client

`bash scripts/build_go.sh` builds three commands into `dist/go/` (version from
`pyproject.toml`). `scripts/release_go.sh` publishes them under **stable,
unversioned names** so `releases/latest/download/<name>` always resolves to the
current release:

| Binary | What it is |
|--------|------------|
| `flashcli-<os>-<arch>` | CLI: pull/run/serve/models/cache/… |
| `flashserver-<os>-<arch>` | Resident scheduler + local console (`127.0.0.1:8790`, `docs/openapi.yaml`) |
| `flashserver-setup-<os>-<arch>` | Installer backend: Linux systemd, Windows WSL2 distro/task/firewall |

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

### Releases

Releases are cut from **`main`** (stable) only. **Never publish an intermediate release
from `dev`.** Validate host changes by building from `dev` locally — `bash install.sh
--from-source --branch dev`, or `bash scripts/build_go.sh` + install the binary. Note
`install.sh --branch dev` **without** `--from-source` still installs the latest
*published* release, so it does **not** exercise dev host code.

Host releases are **incremental**: keep every published release and tag; remove only
unpublished test/draft releases.

**Host (Go) release checklist:**

1. Bump **both** `[project].version` in `pyproject.toml` and `version` in `desktop/Cargo.toml` on `dev` (desktop uses the three-part prefix, e.g. `1.0.9`); commit (`chore(release): bump version to X`). Packaging fails if they diverge. The host version is `X.Y.Z.YYYYMMDD` (no dots in the date); the release tag is `v<version>` (e.g. `v1.0.9.20261120`).
2. Sync `dev` → `main` (squash-and-record, above) so `main` carries the validated commit. Before tagging, also check the live FlashHub index layout (index JSON only, a few KiB): `FLASHCLI_FLASHHUB_LIVE=1 pytest tests/test_flashhub_index_contract.py`.
3. On Windows from `main`, build the installer:
   `powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1`
   (client + Go assets + `flashcli-desktop-setup-windows-amd64-v<version>.exe`; use `-GoBin` if `go` is not on PATH).
   To embed exactly the published binaries (or when Go is not installed on Windows), build them first with
   `bash scripts/build_go.sh` and pass `-SkipGo`; Go builds are reproducible (`-buildvcs=false`).
4. On Linux/macOS (or Windows Git Bash) from `main`, publish both hosts in one command:
   `bash scripts/release_go.sh --upload --notes-file <notes.md> --windows-installer dist/windows/flashcli-desktop-setup-windows-amd64-v<version>.exe`
   The script requires a clean `main` equal to `origin/main`, creates/pushes tag `vX` at HEAD, builds the Linux/Windows Go assets, uploads them plus the Windows installer, and fails if either GitHub or Gitee upload fails. Use `FLASHCLI_RELEASE_TARGET` only for a different release branch; `--allow-non-target` is for tests only.
   The Linux assets are reproducible; the Inno Setup installer is **not** byte-reproducible, so build it once and do not rebuild it after uploading — GitHub/Gitee display the uploaded asset SHA256.
5. Write release notes per the standard below on **both** platforms. `--notes-file` uses the same body for GitHub and Gitee; if omitted, the script uses a minimal generated note.
6. **Gate:** before step 4 (publishing), run the full acceptance gate on `main`: `bash scripts/verify_e2e.sh --heavy --network`. It must be all green; `release_go.sh --upload` refuses without the matching `dist/e2e-pass.json`. Then verify the published assets in a clean environment: `bash scripts/verify_release.sh --version X` (isolated prefix; add `--mirror` for Gitee).
7. Sanity-check the published Windows installer name/SHA256 and that `flashcli-linux-{amd64,arm64}` + `flashserver-*` assets are present on both hosts.
8. Published asset names are **stable and unversioned** (the release tag carries the version). Share stable links: `https://github.com/aodianyun/flashcli/releases/latest/download/<name>` and `https://gitee.com/aodiansoft/flashcli/releases/download/latest/<name>`. Do not add `-v<version>` to published asset names.

- **Bundles**: follow the maintainer checklist below and [docs/bundle_builder_guide.md](docs/bundle_builder_guide.md).

#### Release notes standard

Concise; **Features** and **Fixes** only. Bold the key terms. Same text on GitHub and Gitee; host releases are **incremental** (keep previous releases/tags).

```markdown
# flashcli <version>

<one-line overview; bold the headline>

## Features
- **<area>**: <what changed, user-visible>

## Fixes
<!-- optional: only behavior broken in vPREV; omit this section when empty -->
- **<area>**: <what was broken → fixed>

**Full Changelog**: <compare or commits link>
```

Rules: short bullets, no raw commit dump, no extra sections; **English only** — no Chinese UI labels or translated summary lines; use English action names (Install, Start, Re-sync, Logs, Settings). Do not repeat the asset list or sha256: GitHub/Gitee render the uploaded assets automatically.

**Write against the previous release, not against the commits.** The body is a
comparison: every bullet must be traceable to a difference between the previous
published tag (`vPREV`) and the new one (`vNEW`). Commit messages are raw
material only. **Omit `## Fixes` entirely when no `vPREV` behavior was broken**;
fixes made while building a feature introduced in `vNEW` belong inside that
Feature bullet.

Procedure:

1. `git log --oneline vPREV..vNEW` — understand what happened (do not copy it).
2. `git diff --stat vPREV..vNEW` and review the user-visible surface (commands,
   flags, APIs, manifests, installers). For each bullet ask: *could a user of
   `vPREV` have done this before?*
3. Classify honestly:
   - **Features** — capabilities that did not exist in `vPREV` (new commands,
     new components, changed defaults, new asset/format contracts).
   - **Fixes** — behavior that was **broken in `vPREV`** and now works. Include
     the observed failure (error text / symptom), not the internal commit.
   - Drop internal churn from developing unreleased code (fixes made while
     building a brand-new component are part of that feature, not fixes for
     `vPREV` users), refactors with no visible effect, and test/doc-only work.
4. Verify each claim against the diff or a real run; remove anything you cannot
   demonstrate. Prefer concrete user outcomes ("`du` counted hardlinked layers
   per runtime") over internal names.
5. End with the compare link `.../compare/vPREV...vNEW`. Do not repeat the asset
   list or sha256 — GitHub/Gitee render the uploaded assets automatically.

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
- **English is authoritative; keep the `*.zh-CN.md` mirror in sync** in the same change (same directory). Missing/outdated zh mirrors are a bug.
- **Delete or fix outdated content** instead of appending. Prefer editing the authoritative doc over creating a new one; avoid doc proliferation.
- **One concept, one home.** Do not duplicate a spec across docs — link to the authoritative one. A plan must not redefine behavior; the spec wins.
- **Prefer tables and small diagrams** over prose when clearer.
- **Verify relative links** after moving/renaming files (plans refer to root specs as `../<spec>.md`).
- **When behavior changes**, update together: the authoritative spec (`docs/*.md`), the affected bundle `README`/`BUILD`, and `docs/environment.md` if env vars changed.

## Reporting issues

Include:

- `flashcli doctor` output
- `flashcli models show <preset>` when native selection fails
- GPU model, driver / CUDA userland, Python version
- For bundle build failures: relevant log excerpt from `scripts/run_bg.sh` or Docker matrix build

## License

Contributions are accepted under the project license (Apache-2.0, see `pyproject.toml`).
