# Documentation standard

<p align="right"><strong>English</strong> · <a href="documentation_standard.zh-CN.md">简体中文</a></p>

Authoritative rules for where documentation lives, how it is named, and how it
is kept in sync. Follow this standard for every new or moved document.

## 1. Directory layout

| Location | Contents |
|---|---|
| `docs/` | Authoritative specifications, standards, user guides, and architecture. One concept per file. |
| `docs/plans/` | Delivery plans and milestone checklists. Plans are **not** behavior contracts. |
| `docs/README.md` / `docs/README.zh-CN.md` | Documentation index; every document must be listed. |
| Root `README.md`, `AGENTS.md`, `CONTRIBUTING.md` | Project overview and contributor rules (not feature specs). |

Do not create new subdirectories under `docs/` without updating this standard
and the index.

## 2. Naming

| Kind | Pattern | Example |
|---|---|---|
| Authoritative contract | `<area>_<topic>_spec.md` | `flashserver_gateway_scheduler_spec.md` |
| Delivery plan | `plans/<area>_<topic>_plan.md` | `plans/flashserver_gateway_scheduler_plan.md` |
| Standard / format | `<topic>_standard.md` | `bundle_publish_standard.md` |
| Guide / tutorial | `<topic>_guide.md` | `bundle_builder_guide.md` |
| API reference | `<area>-api.md` | `flashserver-api.md` |
| Architecture / module map | `architecture.md`, `module_layers.md` | — |

Rules:

- Use lowercase `snake_case`; no spaces, dates, versions, or author names.
- The `flashserver` area prefix is required for flashserver contracts, plans,
  and API docs (`flashserver_*`).
- A plan and its contract share the same `<area>_<topic>` stem.
- English is the base name; the Chinese mirror appends `.zh-CN.md` **in the same
  directory** (for example `plans/foo_plan.zh-CN.md`).

## 3. Authority

- **Specs** in `docs/` describe required behavior. Code, tests, and plans must
  not contradict them. A behavior change requires a spec update first.
- **Plans** in `docs/plans/` describe delivery order, milestones, tests, and
  exit criteria. They may be adjusted without changing the contract; when a
  plan and a spec disagree, the spec wins.
- **Standards** (`*_standard.md`) define formats (manifest, app, execution ABI).
- **Guides** explain how to use a stable contract; they must not invent rules.

## 4. Language mirrors

- Every English document has a `.zh-CN.md` mirror in the same directory unless
  it is generated or a third-party file.
- Update both versions in the same change. Keep headings, tables, and code
  blocks structurally aligned; translate prose, not identifiers, paths, or
  command output.
- The top of each file links to its mirror.

## 5. Index and links

- Add every document to `docs/README.md` and `docs/README.zh-CN.md` with a
  one-line purpose and audience.
- Use relative Markdown links. From `docs/plans/`, refer to a root spec as
  `../<spec>.md`; link the zh mirror explicitly.
- Do not link to generated files, `dist/`, build output, or external clones.
- Run the documentation link check (or an equivalent) before committing.

## 6. Content rules

- One concept per document; delete or fix outdated content instead of layering
  caveats.
- Lead with the contract, then details, then examples.
- Keep model-specific behavior in bundle docs, not host docs.
- Plans include: goal, workstreams/milestones, deliverables, tests, exit
  criteria, and compliance rules.
- Do not duplicate a spec inside a plan; link to it.

## 7. Checklist for a documentation change

- [ ] Correct directory and file name per §1–§2.
- [ ] English + zh-CN mirror updated together.
- [ ] `docs/README.md` and `docs/README.zh-CN.md` updated.
- [ ] Relative links resolve from the file's directory.
- [ ] Spec/plan authority is clear (§3).
- [ ] Outdated content removed or corrected.
- [ ] Links checked; no broken paths.
