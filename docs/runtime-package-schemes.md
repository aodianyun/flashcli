# flashcli Runtime Package Schemes (Meeting Notes)

<p align="right"><a href="runtime-package-schemes.zh-CN.md">简体中文</a></p>

**Problem:** One zip ships all `lib/*.so` envs; users often need only one GPU env.  
**Boundary:** flashcli loads bundles, installs deps, fetches weights, calls `entry` — not model logic.

**Env key (all schemes):** `sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}` — e.g. `sm120-cu130-linux-x86-py312`

---

## Current

| | |
|--|--|
| **Core** | Publisher ships py + multi-env so in one zip; client downloads all, runtime picks matching so from `lib/`. |
| **Bundle** | `flashcli-bundle.json`, `run.py`/`serve.py`, `flash_rt/`, **`lib/` multi-env `*.so`**; weights optional. |
| **flashcli** | Download zip → unpack → install deps → load so from `lib/` by env key → weights → `entry`. |
| **Publisher** | Build so per supported env into `lib/`, one zip via `release_bundle.sh`. |
| **Client so load** | Full tree under `~/.flashcli/bundles/<preset>/`; `activate` selects tagged `lib/*.so`. |

---

## Improvement A: Split download (publisher still builds so)

| | |
|--|--|
| **Core** | Same build as today (so per model-supported env in `lib/`); **ship** as base zip (no so) + per-env native zip. |
| **Bundle (logical)** | Same as current full layout. |
| **Bundle (download)** | ① base: json + py + `flash_rt/`; ② native: only `*.so` for one env key. |
| **flashcli** | Fetch base → detect env key → fetch native zip → merge into `bundle_root/lib/` → rest unchanged. |
| **Publisher** | Same multi-env compile; publish `bundle-base.zip` + `bundle-native-<env-key>.zip`. |
| **Client so load** | Merged `lib/` under bundle cache; same selection as current. |

---

## Improvement B: flashcli hosts FlashRT Release runtime so

| | |
|--|--|
| **Core** | so built/published by flashcli per **FlashRT Release × env key**; model bundle has **no** so; publishers use only flashcli-supported Releases. |
| **Bundle** | manifest + `flashrt_version`, entry, `flash_rt/`; **no `lib/*.so`**. |
| **flashcli** | Maintain Release matrix; publish support list; download so to `~/.flashcli/runtimes/<version>/<env-key>/`; inject + deps + weights + `entry`. |
| **Publisher** | Dev/test on supported Release; pack py only; set `flashrt_version` in manifest. |
| **Client so load** | Thin bundle + fetch flashcli runtime so by `flashrt_version` + env key. |

---

## Comparison

| | Current | A: split download | B: flashcli runtime |
|--|---------|-------------------|---------------------|
| **Who builds so** | Publisher | Publisher | **flashcli** |
| **Model zip has so** | Yes (all envs) | Built yes; download no | **No** |
| **Client download** | One zip | base + native | thin bundle + runtime so |
| **Publisher ship** | One zip | base + per-env native | py + `flashrt_version` only |

---

## Open questions

1. Stay on current vs adopt **A** first?  
2. For **B**: first FlashRT Release/ref and env matrix scope?  
3. Formal FlashRT Release tags?  
4. New manifest fields: split layout (A), `flashrt_version` (B)?
