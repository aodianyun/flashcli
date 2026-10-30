# flashcli Model Bundle publish standard (format_version 4)

<p align="right"><strong>English</strong> · <a href="bundle_publish_standard.zh-CN.md">简体中文</a></p>

External specification for **third-party bundle authors**: directory layout, `flashcli-bundle.json` fields, entry conventions, build provenance, and native artifact naming required when publishing to FlashHub.

---

## 1. Overview

| Concept | Description |
|---------|-------------|
| **Model Bundle** | A published inference runtime artifact: manifest + Python entry + optional `flash_rt/` + environment-scoped `.so` files |
| **format_version** | **4** |
| **protocol_version** | `flashcli-bundle` protocol API version; currently **1** |
| **Weights** | **Not** shipped in the bundle; declared in the manifest and fetched on first run |
| **Version** | Pinned by the FlashHub ref (`flashcli-bundle/<name>:<version>`), not by a version file |
| **Build provenance** | Recorded as `build.sources[]` (`name` + `source` + `commit`) in the published manifest |

**Python vs native-only bundles.** A Python bundle uses `defaults.entry` plus its `flash_rt/` tree. A **native-only** bundle sets `entry.kind` to `native-abi` or `native-exec` (see [bundle_execution_abi.md](bundle_execution_abi.md) §6–7): it ships **no** Python entry and **no** `flash_rt/`, and places its C libraries under `runtime/<runtime-dir>/substrate/`.

**v4 model.** One bundle = one model + one execution implementation. Platform differences live in `environments`. `variants`, `backends`, and `entries` are not valid in v4; use separate bundles for different models/backends.

End users resolve bundles via inline refs (`flashcli-bundle/<name>:<version>`). flashcli downloads `flashcli-bundle.json` first, selects the host environment, then downloads only the matching `runtime/<runtime-dir>/` tree.

---

## 2. FlashHub publish layout

Upload the **entire publish root** (preserve relative paths). The FlashHub semantic API returns `data.files[]` with `download_url`, `file_name`, `file_size`, and `md5_hash` per file; paths in `download_url` must match the tree below.

### 2.1 Single environment (example: pi05_libero)

```text
my_bundle/                              ← upload root (version directory contents)
├── flashcli-bundle.json                ← required; fetched first
├── run.py                              ← entry.run module
├── _pi05_compat.py                     ← bundle helper (optional; ship with source)
├── flash_rt/                           ← FlashRT Python tree (no .so inside)
│   ├── __init__.py
│   ├── api.py
│   └── …
└── runtime/
    └── sm120-cu130-linux-x86_64-py312/ ← runtime directory name is arbitrary
        ├── flash_rt_kernels-{abi}-sm120-cu130-linux-x86_64-py312.so
        └── flash_rt_fa2-{abi}-sm120-cu130-linux-x86_64-py312.so
```

### 2.2 Multiple environments in one bundle

`environments` is the only platform matrix. OS/GPU/CUDA/Python differences belong in environments, not in separate refs.

```text
my_bundle/
├── flashcli-bundle.json
├── run.py
├── flash_rt/
└── runtime/
    ├── sm89-cu124-linux-x86_64-py312/
    │   ├── flash_rt_kernels-…-py312.so
    │   └── flash_rt_fa2-…-py312.so
    └── sm120-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-py312.so
        └── flash_rt_fa2-…-py312.so
```

### 2.3 Minimal publish package (required)

The publish tree MUST be minimal, not merely free of build scripts:

- Include only the manifest, entry modules/helpers, `flash_rt/` modules reachable from the entry, and the `runtime/<runtime-dir>/` cells declared by `environments`.
- `flash_rt/` MUST be staged from the FlashRT tree by dependency need. Do not ship unrelated models, frontends, tests, reference implementations, examples, docs, caches, or unused optional modules.
- A bundle may include optional modules only when a manifest-declared option or environment can reach them. "Just in case" files are not publishable.
- A current-environment release contains exactly that one runtime cell; a full matrix contains exactly the cells listed in `environments`.

Pack/build tooling owns this pruning: bundle build scripts MUST stage a minimal `flash_rt/`, and `pack` MUST copy only `RELEASE_PACK_FILES` + the selected runtime cell.

### 2.4 Must not appear in the publish package

| Path / file | Reason |
|-------------|--------|
| `flash_rt_*.so` at bundle root | Native libs must live under `runtime/<runtime-dir>/` |
| Dev-only files (`build.sh`, `.build-*`, tests, refs, examples, docs, caches) | Not required at inference time |
| Unused `flash_rt` model/frontend/backend modules | Not reachable from the entry; increases package size |
| `flash_rt/` `.so`/`.pyc`/`__pycache__` | `flash_rt/` is Python source only |
| Model weight checkpoints | Declared in manifest `weights` / `extra_weights`; fetched externally |
| Top-level `runtime`, `variants`, `backends`, `entries` | v4 uses `environments`; these fields are not part of v4 |

### 2.4 Preset refs (for integrators)

```text
flashcli-bundle/<name>:<version>
```

Examples:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.5
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0
```

- OS/GPU/CUDA/Python are selected from `environments` by the host; they are **not** part of the ref.
- Local dev: `flashcli run bundles/<name>` (directory must contain `flashcli-bundle.json`).

Full ref syntax: [model_bundle_standard.md](model_bundle_standard.md).

---

## 3. `flashcli-bundle.json` reference

### 3.0 Author manifest and generated artifacts

**`flashcli-bundle.json` in the bundle source tree is authoritative and complete.** Publishers own all author fields (`defaults`, `environments` non-runtime fields, etc.), edited by hand in git and reviewed in PRs. Build / pack / release tooling **must not modify** this file.

Generated artifacts (never committed):

| File | Written by | Contents |
|------|-----------|----------|
| `.build/manifest-overlay.json` | `build.sh` / matrix finalize | build metadata: `build`, scanned runtime cells, `python_abi` |
| `dist/flashcli-bundle.json` | `pack.sh` | publishable manifest = author manifest + selected runtime mapping + `build` provenance |

Script contracts:

- **build / matrix cell** MAY add tagged native libs (`lib/`, or `runtime/<env>/substrate/` for native-only) and MAY write `.build/manifest-overlay.json`; it MUST NOT modify `flashcli-bundle.json`.
- **pack** reads the author manifest read-only, copies the selected native cell(s) into `runtime/`, merges `build` from the overlay, and writes the merged manifest only to `dist/flashcli-bundle.json`.
- **pack default** is the current host environment only. Use `--all-envs` / `--verify-matrix` for a full matrix release.
- End users and FlashHub consume **`dist/flashcli-bundle.json`**, never the overlay alone.

### 3.1 Global fields

| Field | Required | Description |
|-------|----------|-------------|
| `format` | yes | Must be `"flashcli-model-bundle"` |
| `format_version` | yes | Must be **4** |
| `protocol_version` | yes | Must be **1** (matches the shipped `flashcli-bundle` protocol) |
| `name` | yes | Bundle id (descriptive only); matching the FlashHub repo name is a readability convention |
| `description` | recommended | Human-readable summary |
| `defaults` | yes | Model-wide configuration shared by all environments |
| `environments` | yes | Non-empty env-key → platform overrides; every entry requires `runtime` |
| `build` | generated | FlashRT/build provenance; written into `dist/` by pack |
| `runtime_abi_version` | conditional | Required for `native-abi`; must be **1** |
| `exec_protocol_version` | conditional | Required for `native-exec`; must be **1** |
| `variants` / `backends` / `entries` | forbidden | v4 has one model and one implementation; split bundles instead |

### 3.2 `defaults.entry`

```json
"entry": {
  "run": {
    "kind": "python",
    "module": "run",
    "attr": "RunEngine"
  },
  "serve": {
    "kind": "python",
    "module": "serve",
    "attr": "ServeEngine"
  }
}
```

| Subfield | Description |
|----------|-------------|
| `run` / `serve` | Capability; `run` enables `flashcli run`, `serve` enables `flashcli serve` |
| `kind` | `python` (default), `native-exec`, or `native-abi` |
| `module` | Python module name relative to the bundle root (Python only) |
| `attr` | Class/callable name (`RunEngine`/`ServeEngine` or script `main`) |
| `mode` | `engine` (default) or `script` (Python only) |

A capability has exactly one implementation. Native backends use the sibling `native` block defined in [bundle_execution_abi.md](bundle_execution_abi.md).

### 3.3 `defaults.python_abi`

```json
"python_abi": "312"
```

- Bundle venv Python ABI as a three-digit string.
- Must match the `-py{PY}` suffix in every environment key.
- Omit for native-only bundles; their env keys have no Python suffix.
- An environment may override it only when that platform really uses another ABI.

### 3.4 `defaults.python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": ["numpy", "safetensors", "transformers<4.56", "pillow"]
}
```

| Key | Description |
|-----|-------------|
| `torch` | PyTorch wheel; `index: "auto"` selects the CUDA index from the host |
| `pip` | Additional pip packages |

An environment replaces this block completely when it defines `python_dependencies`.

### 3.5 `defaults.env`

Engine-mode environment variables applied before the entry runs. Values may use `{models_dir}` and `{bundle_root}`. An environment merges its own `env` map over defaults. Script mode does not apply `defaults.env`; it receives the `FLASHCLI_*` variables in §4.5.

### 3.6 `defaults.weights`

```json
"weights": {
  "source": "huggingface",
  "repo": "lerobot/pi05_libero_finetuned_v044",
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "require_norm_stats": true
}
```

| Field | Description |
|-------|-------------|
| `source` | `huggingface` or `modelscope` |
| `repo` / `revision` | Model id + **full 40-character commit SHA (required for releases)** |
| `allow_patterns` | Optional file filter; omit for the full repo |
| `require_norm_stats` | Set `true` for VLA policies that need norm stats |
| `weights_dir` | Optional relative subdirectory; **default is unset** |

When `weights_dir` is unset, the main weights use the shared weights-store root. The key is derived from `source + repo + revision` (readable dir + hash), so identical weights share a directory and different revisions never collide.

**Release requirement:** `weights.revision` MUST be an immutable full commit SHA. `main`, `master`, branch names, and moving tags are invalid for a published bundle. Pin the exact commit used for validation so the cached weights and the published bundle stay reproducible. `extra_weights.*.revision` follows the same rule.

Do not set `weights_dir: "checkpoint"` for new v4 bundles unless an explicit layout is required.

### 3.7 `defaults.extra_weights`

```json
"extra_weights": {
  "tokenizer": {
    "source": "huggingface",
    "repo": "Qwen/Qwen3-1.7B",
    "revision": "0123456789abcdef",
    "allow_patterns": ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]
  }
}
```

| Field | Description |
|-------|-------------|
| `source` / `repo` / `revision` | Sidecar repo coordinates; `revision` must be a full immutable commit SHA |
| `allow_patterns` / `require_any_patterns` | Download/readiness filters |
| `weights_dir` | Optional relative path; **default `extra/<key>`** under the main weights store |
| `require_norm_stats` | Optional readiness condition |

`weights_dir` must be relative and must not contain `..`.

### 3.8 `defaults.run_options` / `defaults.serve_options`

These are the only source of defaults for bundle-specific CLI flags. `flashcli --help` is generated from them.

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Python keyword / CLI name (snake_case) |
| `type` | no | `string` (default), `integer`, `float`, `boolean` |
| `default` | no | Value when the user omits the flag |
| `help` | yes | Help text |
| `phase` | no | `load` / `predict` (run) or `load` / `warmup` (serve) |
| `flag` | no | Long CLI name; defaults to `name` with `_` → `-` |

Host-provided flags such as `--checkpoint`, `--host`, and `--port` are not declared here. An environment may replace the option list.

### 3.9 `environments`

```json
"environments": {
  "sm120-cu130-linux-x86_64-py312": {
    "runtime": "runtime/sm120-cu130-linux-x86_64-py312",
    "env": { "FLASHRT_PRECISION": "fp8" }
  }
}
```

| Subfield | Required | Description |
|----------|----------|-------------|
| `runtime` | conditional | Relative path to a shared runtime directory; optional for pure-Python/CPU environments and required for native entries |
| `match` | fallback only | Multi-dimensional fallback selector (`os`, `arch`, `python_abi`, optional `vendor`, `sm`, `cuda`) |
| `entry` | no | Platform-specific entry override |
| `python_abi` | no | Platform Python ABI override |
| `python_dependencies` | no | Full replacement of defaults |
| `env` | no | Map merged over defaults |
| `weights` / `weights_dir` | no | Platform-specific weights/layout |
| `extra_weights` | no | Platform-specific sidecars |
| `run_options` / `serve_options` | no | Full replacement |
| `post_pull` / `extra_pull` | no | Platform-specific resource handling |
| `runtime_abi_version` / `exec_protocol_version` | no | Native version axes |

An entry without `match` is an exact env key. Multiple exact env keys may point to the same `runtime` directory; the directory is stateless. A missing/empty `runtime` means pure Python (CPU fallback): no native `.so` is loaded.

#### 3.9.1 Fallback matching

```json
"nvidia-linux-py312": {
  "runtime": "runtime/rtx-fat-linux-py312",
  "match": {
    "os": "linux",
    "arch": "x86_64",
    "python_abi": "312",
    "vendor": "nvidia"
  }
},
"cpu-linux-py312": {
  "match": {
    "os": "linux",
    "arch": "x86_64",
    "python_abi": "312",
    "vendor": "cpu"
  }
}
```

- Exact env key wins.
- Fallbacks are considered only when no exact key matches.
- All fallbacks require `os`, `arch`, and `python_abi`.
- More match dimensions = higher priority. No `priority` field.
- Two fallbacks with the same specificity that can match the same host are invalid and MUST fail `bundle validate`/`pack`.
- Mutually exclusive fallbacks (e.g. `vendor: nvidia` vs `vendor: amd`) are allowed.
- `runtime` may be omitted for a CPU fallback.

### 3.10 Build provenance (which sources built this bundle?)

Published manifests record the immutable source repositories used to build the bundle. The schema is extensible beyond FlashRT:

```json
"build": {
  "sources": [
    {
      "name": "flashrt",
      "source": "https://github.com/flashrt-project/FlashRT.git",
      "commit": "66b18eb766e73e2fcad406bc622bd3bfd70664c1"
    },
    {
      "name": "wan",
      "source": "https://github.com/Wan-Video/Wan2.2.git",
      "commit": "0123456789abcdef0123456789abcdef01234567"
    }
  ]
}
```

- `name` is a stable identifier (`flashrt`, `flashrt-nexus`, `wan`, …); `source` is the repository URL; `commit` is the full 40-character commit SHA.
- Include every source that contributes runtime/Python artifacts. `flashrt` is required for bundles built on FlashRT.
- All `environments` in one bundle must use the same `build.sources` list. If a runtime cell needs a different source/commit, publish it as a separate bundle.
- Do **not** publish generated details such as `runtime_version`, `build_id`, `target`, `features`, `native_artifact_tag`, or tags. They remain in the maintainer-only `.build/manifest-overlay.json`.
- `pack` writes this minimal object from the overlay. If an older overlay has no `sources`, pack synthesizes `flashrt` from the overlay/`git remote get-url origin` + `git rev-parse HEAD`.
- Read `dist/flashcli-bundle.json`, or run `flashcli models show <ref>`.
- `substrate/VERSION` remains a bundle-specific diagnostic, not a substitute for `build`.

### 3.11 Full example

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 4,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 LIBERO VLA",
  "build": {
    "sources": [
      {
        "name": "flashrt",
        "source": "https://github.com/flashrt-project/FlashRT.git",
        "commit": "66b18eb766e73e2fcad406bc622bd3bfd70664c1"
      }
    ]
  },
  "defaults": {
    "entry": { "run": { "module": "run", "attr": "main", "mode": "script" } },
    "python_abi": "312",
    "python_dependencies": {
      "torch": { "package": "torch", "index": "auto" },
      "pip": ["numpy", "pyyaml", "safetensors", "pillow"]
    },
    "run_options": [
      { "name": "prompt", "type": "string", "help": "Task instruction.", "phase": "predict" }
    ],
    "weights": {
      "source": "modelscope",
      "repo": "lerobot/pi05_libero_finetuned_v044",
      "revision": "0123456789abcdef0123456789abcdef01234567",
      "require_norm_stats": true
    }
  },
  "environments": {
    "sm120-cu130-linux-x86_64-py312": {
      "runtime": "runtime/sm120-cu130-linux-x86_64-py312"
    }
  }
}
```

---

## 4. Entry rules

### 4.1 Module location and imports

- `entry.*.module` maps to `{module}.py` (or a package directory) under the bundle root.
- The bundle root is added to `sys.path`; entry and co-located helpers may import each other directly.
- Entry code may depend on **`flashcli_bundle`** only. Do not `import flashcli` (the CLI package).

### 4.2 Native `.so` loading

Before invoking the entry, flashcli:

1. Selects the matching `runtime/<runtime-dir>/` from the selected environment.
2. Registers its `.so` files as extension modules (import names such as `flash_rt_kernels`, `flash_rt_fa2`; no env suffix).
3. Adds the bundle root to `sys.path` so `import flash_rt` and local helpers work.

Script mode must not load `.so` through environment variables or manual `dlopen`.

### 4.3 Engine mode

`RunEngine.load(checkpoint, preset, **options)` loads weights; `RunEngine.predict(...)` runs inference. `ServeEngine` exposes `model_id`, `load`, `warmup`, `chat`, and `chat_stream`. Read defaults via `flashcli_bundle` helpers; do not duplicate manifest defaults in code.

### 4.4 Script mode

`def main(argv: list[str] | None = None) -> int | None` receives bundle flags; weights come from environment variables. `run_options`/`serve_options` are documentation-only in script mode.

### 4.5 Entry environment variables

| Variable | Mode | Description |
|----------|------|-------------|
| `FLASHCLI_CHECKPOINT` | script | Absolute main-weights directory |
| `FLASHCLI_BUNDLE_ROOT` | script | Absolute bundle root |
| `FLASHCLI_PRESET` | script | Preset ref string |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | script | Absolute path for `extra_weights.<key>` |
| manifest `env` / `defaults.env` | engine | Author-defined keys; supports `{models_dir}`, `{bundle_root}` |

Do not rely on internal variables such as `FLASHCLI_RUNTIME_ID`, `FLASHCLI_IN_BUNDLE_VENV`, or host path config.

### 4.6 File mapping

| Manifest | File in publish package |
|----------|-------------------------|
| `entry.run.module: "run"` | `run.py` with `RunEngine` or `main` |
| `entry.serve.module: "serve"` | `serve.py` with `ServeEngine` or `main` |
| Both | Both files are required |

---

## 5. Native `.so` layout and naming

### 5.1 Environment key

```text
{platform_tail}-{os}-{arch}-py{PY}
```

| Segment | Meaning | Example |
|---------|---------|---------|
| `platform_tail` | Opaque platform/runtime id | `sm120-cu130` |
| `os` | OS | `linux` |
| `arch` | CPU arch | `x86_64` |
| `PY` | Python ABI | `312` |

Native-only bundles omit the `-py{PY}` segment. Non-NVIDIA platform tails are allowed (e.g. `gfx942-rocm611`).

### 5.2 Directory rules

1. Native `.so` files live under a runtime directory such as `runtime/<dir>/`; the directory name is arbitrary.
2. Multiple environments may point to the same runtime directory and share the same `.so` files.
3. Do not ship `.so` at the bundle root or under `lib/`.
4. `flash_rt/` contains Python source only, no `.so`, `.pyc`, or `__pycache__`.
5. On sync, end users download the selected runtime directory once, plus the shared source tree.
6. A runtime-less Python environment needs no `flash_rt/` unless the entry imports it.

### 5.3 Filename pattern

```text
{module_base}-{flashrt_abi}-{build_tag}.so
```

- `module_base`: logical import name (`flash_rt_kernels`, `flash_rt_fa2`, …); required.
- `flashrt_abi`: build id.
- `build_tag`: arbitrary readable tag; does not have to equal any env key.
- Prefer one artifact per module per runtime directory. The host loads recognized native extension `.so` files from the selected directory; it does not bind filenames to the selected env key.
- Fat binaries (multiple SM architectures/PTX) are allowed; compatibility is the publisher's responsibility.

### 5.4 Matrix notes

- Each supported `(SM, CUDA, python_abi)` combination gets one environment key.
- All cells should expose the same `module_base` set unless a platform genuinely differs.
- A release may contain one environment (current host) or a full matrix, but the manifest's `environments` must match the uploaded `runtime/` directories exactly.

---

## 6. Pre-publish checklist

- [ ] `format_version: 4`, `protocol_version: 1`
- [ ] `defaults` non-empty; `environments` non-empty
- [ ] Every native environment has `runtime`; pure-Python/CPU environments may omit it
- [ ] No `variants`, `backends`, `entries`, or top-level `runtime`
- [ ] Native entries: `runtime_abi_version` / `exec_protocol_version` set exactly for the declared `kind`
- [ ] `flashcli-bundle.json` at publish root
- [ ] Every Python `entry.*.module` has a matching file and symbol
- [ ] `python_abi` + `python_dependencies` present for Python entries; any `-py` suffix on an env key matches `python_abi`
- [ ] Every non-empty `environments.<key>.runtime` has a directory with at least one recognizable native `.so` (or `substrate/*.so` for native-only)
- [ ] Shared runtime directories are referenced by compatible environments; no ambiguous fallback
- [ ] No stray `.so` at bundle root, under `lib/`, or inside `flash_rt/`
- [ ] `flash_rt/` present when a Python environment has a native runtime; absent for runtime-less CPU and native-only bundles
- [ ] `build.sources[]` present with `name` + `source` + `commit`; all environments use the same sources
- [ ] Every `weights` and `extra_weights` revision is a full immutable commit SHA (no `main`/`master`/branch/tag)
- [ ] `flashcli bundle validate` passes
- [ ] Smoke `flashcli run` / `serve` on the target GPU
- [ ] `dist/` is minimal: no dev artifacts, tests, refs, caches, unused model/frontend modules, or weights
- [ ] `flash_rt/` contains only modules reachable from the entry and manifest-declared options
- [ ] After upload, `bundle.repo` returns the full `files[]` list including `.so` URLs

---

## 7. Related docs

| Doc | Content |
|-----|---------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | 简体中文 |
| [model_bundle_standard.md](model_bundle_standard.md) | Refs and end-user runtime flow |
| [bundle_execution_abi.md](bundle_execution_abi.md) | Native entry contracts |
| [bundle_builder_guide.md](bundle_builder_guide.md) | Maintainer build/release workflow |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
