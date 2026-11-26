# Development verification standard

<p align="right"><strong>English</strong> · <a href="development_verification_standard.zh-CN.md">简体中文</a></p>

This is the authoritative process for verifying a change **before it is merged
to `dev`**. Release gating is separate: see
[release_verification_standard.md](release_verification_standard.md).

## 1. Branch and commit policy

- Default: branch from `dev` (`feat/<topic>` or `fix/<topic>`), open a PR into
  `dev`.
- Local-only, unpushed maintenance explicitly requested by the maintainer may be
  committed directly on `dev`. Do not push those commits until the normal
  review/verification path is agreed.
- Never commit directly to `main`. `dev` → `main` is maintainer-approved
  squash-and-record; see [CONTRIBUTING.md](../CONTRIBUTING.md#git-workflow).
- One logical change per commit. Do not mix unrelated code, refactors, and docs.

## 2. Prerequisites

| Requirement | Notes |
|---|---|
| Go >= 1.24 | `GO=/path/to/go` overrides the binary for the helper scripts. |
| `flashcli-bundle` editable install | `pip install -e "./flashcli-bundle"` (`[infer,test]` for infer tests). |
| Rust MSVC (desktop only) | `cargo test` from `desktop/`. |
| Linux or WSL | Acceptance tests run the real Linux binaries. |

Build only the binaries the tests use:

```bash
bash scripts/build_dev_bins.sh
```

This produces `dist/go/flashcli-linux-amd64` and
`dist/go/flashserver-linux-amd64`. Do **not** run `scripts/build_go.sh` for
testing: it builds release assets for Linux amd64/arm64 and Windows setup, none
of which pytest uses.

## 3. Verification tiers

| Tier | Command | When |
|---|---|---|
| **1 — code** (default) | `cd go && go test ./...` · `pytest tests/` · `gofmt -l .` | Every change / PR |
| **2 — acceptance** (offline) | `bash scripts/verify_e2e.sh` | CLI, daemon API, scheduler, cache, or desktop-facing behavior |
| **2h — heavy acceptance** | `bash scripts/verify_e2e.sh --heavy` | Before merging to `main` or cutting a release candidate |

Tier 3 (`--heavy --network`) is the release gate and is defined in
[release_verification_standard.md](release_verification_standard.md).

### Tier 1 — code

```bash
cd go
gofmt -w .
go build ./...
go test ./...

pytest tests/            # protocol/infer + conformance; excludes bench, release, network
pytest tests/bench/      # only when changing bench helpers
cd desktop && cargo test # only when changing the desktop client
```

Tier 1 does not start the real daemon and does not verify the installed binary
surface. Release-only build checks (`tests/test_build_go.py`, marked `release`)
run in the release gate; PyPI venv tests (`tests/test_bundle_requirement_import.py`,
marked `network`) run in Tier 2h.

### Tier 2 — real binaries, offline

```bash
bash scripts/verify_e2e.sh
```

`verify_e2e.sh`:

1. builds the two dev binaries with `scripts/build_dev_bins.sh`;
2. exports `FLASHCLI_GO_BIN` and `FLASHSERVER_BIN`;
3. runs `pytest tests/acceptance` with `FLASHCLI_ACCEPTANCE=1`.

Coverage:

- real `flashcli version/doctor/bundle validate/models show`;
- offline FlashHub sync through a local HTTP index (both CDN layouts);
- real `flashserver`: preload → gateway request → logs → unload;
- API/settings/error-path checks that need a real HTTP server.

It does not run Python bundle inference; that is the `--heavy` tier.

### Tier 2h — heavy acceptance

```bash
bash scripts/verify_e2e.sh --heavy
```

Adds real `run` on v3 and v4 Python bundles plus a native bundle. This creates
bundle venvs and can take several minutes; run it before `main` merges and
release candidates, not on every edit. Network-marked PyPI requirement tests
belong to Tier 3, not this tier.

## 4. Contract checks by change type

| Change | Required work |
|---|---|
| HTTP API (`/v1/*`, `/api/v1/*`) | Update `go/internal/server/openapi.yaml` (the **single** contract; it is embedded and served at `/openapi.yaml`). Update `docs/flashserver-api.md` + `.zh-CN.md`, `go/internal/server/web/docs.html`, the desktop caller, and an acceptance/unit test. Grep the old path and confirm it returns 404. |
| CLI command/flag | Command help + CLI tests; `tests/conformance/test_command_parity.py` if the command surface changed. |
| Desktop behavior | `desktop/README.md`, `docs/flashserver-desktop.md` + `.zh-CN.md`, `cargo test`; build for UI changes. |
| Bundle manifest / execution ABI | Authoritative spec + `.zh-CN.md`, bundle `README`/`BUILD`, `flashcli bundle validate`, conformance fixtures. |
| Docs only | [documentation_standard.md](documentation_standard.md) checklist. |

Do not land an API change with only the handler and a unit test: the OpenAPI
contract, API index, console reference, desktop caller, and zh-CN mirror are
part of the change.

## 5. Stale-binary and environment rules

- Acceptance refuses `dist/go` binaries older than `go/` sources. With
  `--no-build`, `verify_e2e.sh` fails fast instead of silently testing old code.
- `FLASHCLI_GO_BIN` / `FLASHSERVER_BIN` explicitly set by the caller are
  trusted; the freshness check is skipped.
- `PYTHON_BIN=/path/to/python` selects the interpreter for `verify_e2e.sh`
  (useful when pytest lives in a venv).
- `FLASHCLI_ACCEPTANCE_HOME` reuses the venv/uv cache between runs (default
  `/tmp/flashcli-acceptance`).

## 6. Definition of done for a PR

- [ ] Tier 1 commands pass.
- [ ] Tier 2 passes for API/CLI/daemon/cache changes; Tier 2h passes before
      `main` or an RC.
- [ ] Contract docs and zh-CN mirror updated; removed endpoints return 404.
- [ ] No stale `dist/go` binaries, secrets, weights, or build output committed.
- [ ] Commits are logical Conventional Commits; branch is rebased on `dev`.
- [ ] Documentation links resolve and `docs/README.md` indexes new docs.

## 7. Failure handling

| Symptom | Action |
|---|---|
| Acceptance says the binary is stale | Run `scripts/build_dev_bins.sh`, then rerun. |
| New endpoint returns 405 instead of 404 | Check route ordering/catch-all patterns; add the path to an acceptance test. |
| Docs/API drift | Fix the authoritative contract first, then the index/console/mirror. |
| Flaky or environment-only failure | Reproduce with the same tier; record the command and environment in the PR. Do not mark green without a run. |
