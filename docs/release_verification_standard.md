# Release verification standard

<p align="right"><strong>English</strong> · <a href="release_verification_standard.zh-CN.md">简体中文</a></p>

This is the authoritative process for verifying and publishing a **host
release**. Development checks before merge are separate: see
[development_verification_standard.md](development_verification_standard.md).

## 1. Scope and preconditions

- Releases are cut from **`main`** only. Never publish an intermediate release
  from `dev`.
- `main` must be clean and equal to `origin/main`; the release script enforces
  this.
- Host releases are **incremental**: keep every published release and tag;
  remove only unpublished test/draft releases.
- The release gate must pass for the exact commit being published.

## 2. Versioning

- Bump **both** `[project].version` in `pyproject.toml` and `version` in
  `desktop/Cargo.toml` on `dev`. The desktop value is the three-part prefix
  (for example `1.0.9`); packaging fails if they diverge.
- Host version: `X.Y.Z.YYYYMMDD` (no dots in the date).
- Tag: `v<version>` (for example `v1.0.9.20261120`).
- Commit message: `chore(release): bump version to X`.

## 3. Gate and evidence

```bash
bash scripts/verify_e2e.sh --heavy --network
```

This is Tier 3 from the development standard:

- real binaries and real daemon;
- Python bundle inference (`--heavy`);
- live FlashHub manifest check (`--network`);
- release-only build/install checks (`tests/test_build_go.py -m release`);
- PyPI venv requirement checks (`tests/test_bundle_requirement_import.py -m network`);
- writes `dist/e2e-pass.json` with the current commit, `heavy=true`,
  `network=true`.

`scripts/release_go.sh --upload` refuses to publish unless the marker matches
the exact HEAD and both flags are true. `FLASHCLI_SKIP_E2E_GATE=1` exists only
for pipeline tests; never use it for a real release.

## 4. Release sequence

1. **Bump versions on `dev`** (§2) and commit.
2. **Sync `dev` → `main`** with squash-and-record. This requires explicit
   maintainer approval; do not push `main` without it.
3. **Check the live FlashHub index contract** (index JSON only, a few KiB):

   ```bash
   FLASHCLI_FLASHHUB_LIVE=1 pytest tests/test_flashhub_index_contract.py
   ```

4. **Run the full gate on `main`** (§3). Do not tag or publish on a red gate.
5. **Build the Windows installer from `main`:**

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1
   ```

   This builds the desktop client, the Go assets it embeds, and
   `flashcli-desktop-setup-windows-amd64-v<version>.exe`. Use `-GoBin` if `go`
   is not on PATH. To embed already-built Go assets, run
   `bash scripts/build_go.sh` first and pass `-SkipGo`.
6. **Prepare release notes** (§5) against the previous published release.
7. **Publish from `main`:**

   ```bash
   bash scripts/release_go.sh --upload \
     --notes-file <notes.md> \
     --windows-installer dist/windows/flashcli-desktop-setup-windows-amd64-v<version>.exe
   ```

   The script verifies the gate, clean `main == origin/main`, creates/pushes the
   tag at HEAD, builds/uploads the Go assets and Windows installer, and fails if
   either GitHub or Gitee upload fails.
8. **Verify the published assets** in a clean, isolated environment:

   ```bash
   bash scripts/verify_release.sh --version X
   # add --mirror for Gitee / CN mirrors
   ```

9. **Sanity-check** the published installer name/SHA256 and that
   `flashcli-linux-{amd64,arm64}` and `flashserver-*` exist on both hosts.

## 5. Release notes standard

Concise; **Features** and **Fixes** only. Same text on GitHub and Gitee. Write
against the previous published release, not against the commit list.

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

Rules:

- Short bullets; no raw commit dump; no extra sections.
- **English only**; no translated summary lines.
- Do not repeat the asset list or SHA256.
- A **Feature** is a capability absent from `vPREV`; a **Fix** is behavior that
  was broken in `vPREV`.
- Drop internal churn, refactors with no visible effect, and test/doc-only work.
- Verify each claim against the diff or a real run.
- End with `.../compare/vPREV...vNEW`.

## 6. Artifacts and naming

| Artifact | Purpose |
|---|---|
| `flashcli-<os>-<arch>` | CLI: pull/run/serve/models/cache/… |
| `flashserver-<os>-<arch>` | Resident scheduler + local console |
| `flashserver-setup-<os>-<arch>` | Installer backend (Linux systemd, Windows WSL2) |
| `flashcli-desktop-setup-windows-amd64-v<version>.exe` | Windows desktop installer |

- `scripts/build_go.sh` builds **release** Go assets only: Linux amd64/arm64
  plus the Windows setup binary. It is not a test build.
- Published asset names are **stable and unversioned**; the tag carries the
  version. Do not add `-v<version>` to Go asset names.
- The Linux assets are reproducible (`-buildvcs=false`). The Inno Setup
  installer is **not** byte-reproducible: build it once, upload it, and do not
  rebuild it after upload.
- Share stable links:

  ```text
  https://github.com/aodianyun/flashcli/releases/latest/download/<name>
  https://gitee.com/aodiansoft/flashcli/releases/download/latest/<name>
  ```

## 7. Failure and abort rules

| Situation | Action |
|---|---|
| Gate is red | Stop. Fix and rerun; do not tag or publish. |
| `dist/e2e-pass.json` is missing/stale | Rerun the full gate on the exact HEAD. |
| `main` is dirty or ahead/behind `origin/main` | Resolve, re-verify, and rerun the gate if HEAD changed. |
| GitHub or Gitee upload fails | The release script fails; rerun after fixing credentials. Do not hand-edit published assets. |
| Windows installer was already uploaded | Do not rebuild it; rebuild only before upload. |
| A bad release was published | Fix forward with a new version/tag; never rewrite or delete published history. |

## 8. Post-release checklist

- [ ] Full gate passed for the released commit (`heavy=true`, `network=true`).
- [ ] Tag `v<version>` exists at the release commit and is pushed.
- [ ] GitHub and Gitee both have all Go assets and the Windows installer.
- [ ] `verify_release.sh --version X` passes (and `--mirror` for Gitee).
- [ ] Release notes follow §5 on both hosts.
- [ ] Stable download links resolve.
- [ ] The next development cycle starts from an updated `dev`.
