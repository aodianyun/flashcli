# flashcli Model Bundle publish standard (format_version 3)

<p align="right"><strong>English</strong> · <a href="bundle_publish_standard.zh-CN.md">简体中文</a></p>

External specification for **third-party bundle authors**: directory layout, `flashcli-bundle.json` fields, entry conventions, and native artifact naming required when publishing to FlashHub.

---

## 1. Overview

| Concept | Description |
|---------|-------------|
| **Model Bundle** | A published inference runtime artifact: manifest + Python entry + optional `flash_rt/` + environment-scoped `.so` files |
| **format_version** | Only **3** is supported today |
| **protocol_version** | `flashcli-bundle` protocol API version; currently **1** |
| **Weights** | **Not** shipped in the bundle; declared in the manifest (e.g. Hugging Face) and fetched on first run by end users |

End users resolve bundles via inline ref strings (`flashcli-bundle/<name>:<version>[@variant]`). flashcli downloads `flashcli-bundle.json` first, matches the host GPU/CUDA/Python against `runtime` env keys, then downloads only the matching `runtime/<env-key>/` tree.

---

## 2. FlashHub publish layout

Upload the **entire publish root** (preserve relative paths). The FlashHub semantic API returns `data.files[]` with `download_url`, `file_name`, `file_size`, and `md5_hash` per file; paths in `download_url` must match the tree below.

### 2.1 Single preset (example: pi05_libero)

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
    ├── sm89-cu124-linux-x86_64-py312/  ← env key = directory name
    │   ├── flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py312.so
    │   └── flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py312.so
    └── sm89-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-sm89-cu130-linux-x86_64-py312.so
        └── flash_rt_fa2-…-sm89-cu130-linux-x86_64-py312.so
```

### 2.2 Multiple presets sharing one repo (example: qwen_nvfp4)

Same repo, same **`entry`**; `@variant` in the ref selects weights and options from each variant block:

```text
qwen_nvfp4/
├── flashcli-bundle.json
├── run.py
├── serve.py                            ← required when entry.serve is set
├── _qwen_util.py
├── _backend_qwen3.py
├── _backend_qwen36_agent.py
├── …                                   ← Python modules imported by entry
├── flash_rt/
│   └── …
└── runtime/
    └── sm120-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-sm120-cu130-linux-x86_64-py312.so
        ├── flash_rt_fa2-…-sm120-cu130-linux-x86_64-py312.so
        └── flash_rt_fp4-…-sm120-cu130-linux-x86_64-py312.so   ← optional (NVFP4, etc.)
```

### 2.3 Must not appear in the publish package

| Path / file | Reason |
|-------------|--------|
| `flash_rt_*.so` at bundle root | Native libs must live under `runtime/<env-key>/` |
| Dev-only files outside runtime needs (`build.sh`, `.build-matrix/`, non-runtime `dist/` artifacts) | Not required at inference time |
| Model weight checkpoints | Declared in manifest `weights` / variant `weights`; fetched externally |

### 2.4 Preset refs (for integrators)

Users pass an inline ref string — no bundled catalog file:

```text
flashcli-bundle/<name>:<version>[@variant]
```

Examples:

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36
```

- **Single-variant bundle** — ref is `namespace/bundle:version` only.
- **Multi-variant bundle** — users **must** include `@variant` in the ref.
- **Local dev** — `flashcli run bundles/qwen_nvfp4@qwen36` (directory must contain `flashcli-bundle.json`).

Full syntax: [model_bundle_standard.md](model_bundle_standard.md).

---

## 3. `flashcli-bundle.json` reference

### 3.0 Author manifest (do not auto-modify)

**`flashcli-bundle.json` in the bundle source tree is authoritative and complete.** Publishers maintain all product fields (`python_dependencies`, `weights`, `run_options`, …) by hand in git. Build and pack scripts **must not** overwrite this file; they only write `.build/manifest-overlay.json` (build metadata) and merge into **`dist/flashcli-bundle.json`** at pack time. See [bundle_manifest_policy.md](bundle_manifest_policy.md).

### 3.1 Top-level required and recommended fields

| Field | Required | Description |
|-------|----------|-------------|
| `format` | yes | Must be `"flashcli-model-bundle"` |
| `format_version` | yes | Must be **3** |
| `protocol_version` | yes | Must be **1** (matches the `flashcli-bundle` protocol shipped with flashcli) |
| `name` | yes | Bundle id; should match directory / FlashHub repo name |
| `description` | recommended | Human-readable summary |
| `python_abi` | yes | Fixed Python ABI as a three-digit string, e.g. `"312"` = CPython 3.12 |
| `entry` | yes | At least one of `run` or `serve` (see §4) |
| `runtime` | yes | env key → relative path map (see §5) |
| `python_dependencies` | yes | pip deps for the bundle venv (see §3.4) |
| `run_options` | conditional | Required when there is no `variants` and `run` is supported |
| `serve_options` | conditional | Required when there is no `variants` and `serve` is supported |
| `weights` | conditional | Weight source for a single-preset bundle |
| `variants` | conditional | Required when multiple presets share one repo (see §3.3) |
| `post_pull` | no | Hooks after weight download (e.g. tokenizer setup) |

### 3.2 `entry`

```json
"entry": {
  "run":  { "module": "run",  "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

Optional **`mode`**: `"engine"` (default) or `"script"`. Engine mode uses `RunEngine`/`ServeEngine` and the built-in HTTP stack; script mode passes argv (after REF) through to the entry callable (usually `main`). `run_options`/`serve_options` are documentation-only in script mode (`--help`).

Script example:

```json
"entry": {
  "run":  { "module": "run",  "attr": "main", "mode": "script" },
  "serve": { "module": "serve", "attr": "main", "mode": "script" }
}
```

| Subfield | Description |
|----------|-------------|
| `module` | Python module name relative to bundle root (no `.py`), e.g. `"run"` → `run.py` |
| `attr` | Engine mode: class name (`RunEngine`/`ServeEngine`); script mode: callable entry (e.g. `main`) |
| `mode` | Optional: `engine` (default) or `script` |

Capabilities are inferred from `entry`: `run` enables `flashcli run`; `serve` enables `flashcli serve`.

Environment variables injected before entry runs are documented in **§4.4** (engine vs script differ).

### 3.3 `variants` (multiple presets, one repo)

When `variants` is present:

- Top-level `run_options` / `serve_options` / `weights` are **forbidden** (validation fails).
- **Each variant** must define its own complete `run_options`, `serve_options` (when needed), `weights`, etc.

Common variant fields:

| Field | Description |
|-------|-------------|
| `description` | Variant summary |
| `weights_dir` | Subdirectory name under the preset cache for weights |
| `weights` | `{ "source": "huggingface", "repo": "…", "revision": "…" }` |
| `extra_weights` | Additional weights (e.g. Qwen MTP); same shape as `weights`; may add `cache_name`, `allow_patterns` |
| `env` | **Engine mode:** process env before entry runs; `{models_dir}`, `{bundle_root}` (see §4.4.2). Script mode does not apply manifest `env` (see §4.4.1). |
| `run_options` / `serve_options` | Variant-specific CLI options (see §3.6) |

### 3.4 `python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": [
    "numpy",
    "safetensors",
    "transformers<4.56"
  ],
  "pip_nodeps": ["omnivoice"]
}
```

| Key | Description |
|-----|-------------|
| `torch` | PyTorch wheel; `"index": "auto"` lets flashcli pick cu124/cu128 index from host CUDA (**recommended**) |
| `pip` | Additional pip packages (strings with optional version constraints) |
| `pip_nodeps` | Optional; package names installed with `pip install --no-deps` so PyPI does not pull transitive `torchaudio` wheels that conflict with the torch CUDA index. `omnivoice` defaults to `--no-deps` even when omitted |
| `torchaudio` / `torchvision` | When required at runtime, **list explicitly** in `pip`; flashcli installs them from the same CUDA wheel index as `torch` |

The bundle venv Python version is fixed by `python_abi`, independent of the host CLI Python.

### 3.5 `weights` (single preset or inside a variant)

```json
"weights": {
  "source": "huggingface",
  "repo": "lerobot/pi05_libero_finetuned_v044",
  "revision": "main",
  "require_norm_stats": true
}
```

| Field | Description |
|-------|-------------|
| `source` | Supported: `"huggingface"`, `"modelscope"` |
| `repo` / `revision` | Hugging Face model id and branch/commit |
| `require_norm_stats` | Optional; set `true` for VLA policies that need norm stats |

### 3.6 `run_options` / `serve_options`

The **only** source of default values for bundle-specific CLI flags; end-user `--help` is generated from the manifest.

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Python keyword argument passed to the engine (snake_case) |
| `type` | no | `string` (default), `integer`, `float`, `boolean` |
| `default` | no | Value when the user omits the flag |
| `help` | yes | Help text |
| `phase` | no | **run**: `load` → `load()` or `predict` → `predict()`; **serve**: `load` or `warmup` |
| `flag` | no | Long CLI name (without `--`); default is `name` with `_` → `-` |

**Not declared in the manifest** (provided by flashcli): e.g. `--checkpoint`, `--host`, `--port`.

### 3.7 `runtime`

```json
"runtime": {
  "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
  "sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"
}
```

- **Key (env key)** — target environment id (format in §5.1).
- **Value** — path relative to bundle root; **must** start with `runtime/`; matching directory name is recommended.
- Every key in the manifest **must** exist in the publish package with a complete `.so` set.

### 3.8 Full example (single preset, excerpt)

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 LIBERO VLA",
  "python_abi": "312",
  "entry": {
    "run": { "module": "run", "attr": "RunEngine" }
  },
  "python_dependencies": {
    "torch": { "package": "torch", "index": "auto" },
    "pip": ["numpy", "pyyaml", "safetensors", "transformers<4.56", "pillow"]
  },
  "run_options": [
    {
      "name": "prompt",
      "type": "string",
      "default": "pick up the block",
      "help": "Task instruction.",
      "phase": "predict"
    },
    {
      "name": "num_views",
      "type": "integer",
      "default": 2,
      "help": "Number of camera views.",
      "phase": "load"
    }
  ],
  "weights": {
    "source": "huggingface",
    "repo": "lerobot/pi05_libero_finetuned_v044",
    "revision": "main"
  },
  "runtime": {
    "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
    "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"
  }
}
```

Full `variants` example: `bundles/qwen_nvfp4/flashcli-bundle.json` in the repo.

---

## 4. Entry rules

### 4.1 Module location and imports

- `entry.*.module` maps to `{module}.py` (or a package directory) under the bundle root.
- The bundle root is added to `sys.path` at runtime; entry and co-located helpers may import each other directly.
- Entry code may depend on **`flashcli_bundle`** only (manifest, options, protocol types). **Do not** `import flashcli` (the CLI package).

#### 4.1.1 Native `.so` loading (same for engine and script)

Regardless of `entry.*.mode` (**engine** or **script**), flashcli runs **activate** before invoking `RunEngine` / `ServeEngine` or script `main(argv)`:

1. Select the matching `runtime/<env-key>/` from manifest `runtime` using host GPU / CUDA / `python_abi` (see §5).
2. Register `.so` files in that directory as Python extension modules (import names such as `flash_rt_kernels`, `flash_rt_fa2` — **without** the env suffix in filenames; see §5.3).
3. Add the bundle root to `sys.path` so `import flash_rt` and local helpers work.

**Script mode does not** and **should not** load `.so` via environment variables or manual `dlopen`. Import as in engine mode, e.g.:

```python
import flash_rt
from flash_rt import flash_rt_kernels
```

Publish layout and naming are in **§5**; this is unrelated to weight env vars in §4.4.

Running `python run.py` directly (without `flashcli run`) does **not** perform activate; use `flashcli run <ref> …` for validation, or simulate paths/native registration only for local dev.

Recommended imports (engine protocol types; script entry uses only what it needs):

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults, serve_option_defaults
from flashcli_bundle.protocol import ChatRequest, ChatResult, RunEngine, ServeEngine
from flashcli_bundle.preset import Preset
```

### 4.2 `RunEngine` protocol

Class name matches `entry.run.attr` (typically `RunEngine`). Must implement:

| Method | Description |
|--------|-------------|
| `load(checkpoint: Path, preset: Preset, **options)` | Load weights; `**options` includes run_options with `"phase": "load"` |
| `predict(*, prompt: str = "", images: list \| None = None, **kwargs)` | Inference; `**kwargs` includes run_options with `"phase": "predict"` |

Read defaults via `run_option_defaults(bundle, variant=…)` / `option_value()` — **do not** duplicate manifest defaults in code.

### 4.3 `ServeEngine` protocol

Class name matches `entry.serve.attr` (typically `ServeEngine`). Must implement:

| Member | Description |
|--------|-------------|
| `model_id` (property) | Model id exposed on the OpenAI API |
| `load(checkpoint, preset, **options)` | serve_options with `"phase": "load"` |
| `warmup(spec)` | serve_options with `"phase": "warmup"`; CUDA graph warmup, etc. |
| `chat(request: ChatRequest) -> ChatResult` | Non-streaming |
| `chat_stream(request) -> Iterator[ChatChunk]` | Streaming |

### 4.4 Entry environment variables (engine / script)

flashcli writes environment variables to the current process **after weights are validated** and **immediately before** invoking the entry (`RunEngine` / `ServeEngine` or script `main`). Third-party entry code should **only** rely on names listed in this section; other `FLASHCLI_*` values (e.g. `FLASHCLI_RUNTIME_ID`, `FLASHCLI_IN_BUNDLE_VENV`) are internal and **not a stable API**.

`entry.*.mode` determines which variables are set: script mode uses platform `FLASHCLI_*` absolute paths; engine mode uses manifest-declared `env` and a few conventional names.

#### 4.4.1 Script mode (`mode: "script"`)

Entry signature: `def main(argv: list[str] | None = None) -> int | None` (or equivalent). User CLI flags live in `argv` and are parsed by the bundle; weight paths are provided via environment variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `FLASHCLI_CHECKPOINT` | yes | **Main weights** directory (absolute path, cache-validated). |
| `FLASHCLI_BUNDLE_ROOT` | yes | Bundle root (absolute path). |
| `FLASHCLI_PRESET` | yes | Preset ref string (same as CLI positional ref). |
| `FLASHCLI_VARIANT` | no | Set when ref includes `@variant`; usually unset for single-variant bundles. |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | no | One per manifest `extra_weights` entry; `<KEY>` is the uppercased manifest key (non-alphanumeric → `_`). Value is the **absolute path** (validated). |

`extra_weights` key → env name examples:

| manifest `extra_weights` key | Environment variable |
|--------------------------------|----------------------|
| `vocoder` | `FLASHCLI_EXTRA_WEIGHT_VOCODER` |
| `mtp_fp8` | `FLASHCLI_EXTRA_WEIGHT_MTP_FP8` |

Script mode does **not** apply top-level or variant `env` blocks and does **not** expose the global `{models_dir}` cache layout. Read only the variables above.

Native extensions (`.so`) load the same way as in engine mode; see **§4.1.1**. In script mode, use `import flash_rt` / `from flash_rt import flash_rt_*` — no separate env vars for `.so`.

Example `run.py`:

```python
import os
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    ckpt = Path(os.environ["FLASHCLI_CHECKPOINT"])
    bundle_root = Path(os.environ["FLASHCLI_BUNDLE_ROOT"])
    mtp = os.environ.get("FLASHCLI_EXTRA_WEIGHT_MTP_FP8")  # if manifest has extra_weights.mtp_fp8
    ...
    return 0
```

#### 4.4.2 Engine mode (default, omit `mode` or `"engine"`)

Main weights are **not** written to `FLASHCLI_CHECKPOINT`; flashcli passes them as the `checkpoint` argument to `RunEngine.load(...)` / `ServeEngine.load(...)`. Additional paths and assets enter the process via:

| Source | Description | Example names |
|--------|-------------|---------------|
| manifest **`env`** / variant **`env`** | Applied before entry runs; values may use `{bundle_root}`, `{models_dir}` placeholders (expanded to absolute paths). **Keys are author-defined.** | `FLASHRT_QWEN36_MTP_CKPT_DIR`, `MY_AUX_DIR` |
| **`post_pull`** | Runs after weight fetch; prepares ancillary files and may set env. | `FLASH_RT_PALIGEMMA_TOKENIZER` (Pi0.5 PaliGemma tokenizer file) |
| CLI **`--mtp-checkpoint`** | Parsed by flashcli in engine mode only; overrides manifest MTP env. | `FLASHRT_QWEN36_MTP_CKPT_DIR` |

manifest `env` example (Qwen variant, excerpt):

```json
"env": {
  "FLASHRT_QWEN36_MTP_CKPT_DIR": "{models_dir}/qwen_nvfp4/1.0.1@qwen36/mtp_fp8"
}
```

`{models_dir}` expands to the flashcli models cache root (default `~/.flashcli/models`); `{bundle_root}` to the bundle root. Engine entry code reads author-declared keys via `os.environ` inside `load()` or helpers.

#### 4.4.3 Mode comparison

| Topic | Script | Engine |
|-------|--------|--------|
| Main weights | `FLASHCLI_CHECKPOINT` | `load(checkpoint, …)` argument |
| Extra weights | `FLASHCLI_EXTRA_WEIGHT_<KEY>` | manifest `env` or custom keys |
| manifest `env` | **not applied** | **applied** |
| `post_pull` env | `post_pull` may still run to prepare files on disk; script entry should prefer `FLASHCLI_*` above | e.g. `FLASH_RT_PALIGEMMA_TOKENIZER` |
| `run_options` / `serve_options` | `--help` documentation only; flags in `argv` | parsed by flashcli and passed to engine |
| `--checkpoint` | stays in `argv`; also used for validation → `FLASHCLI_CHECKPOINT` | parsed by flashcli → `load()`, no `FLASHCLI_CHECKPOINT` |
| `--mtp-checkpoint` | **not** parsed by flashcli (passed in `argv`); use `FLASHCLI_EXTRA_WEIGHT_*` | sets `FLASHRT_QWEN36_MTP_CKPT_DIR` |

#### 4.4.4 Do not rely on in entry code

| Variable | Reason |
|----------|--------|
| `FLASHCLI_RUNTIME_ID` | internal runtime matrix key at re-exec |
| `FLASHCLI_IN_BUNDLE_VENV` | marks infer subprocess, not business config |
| `FLASHCLI_HOME` / `FLASHCLI_MODELS_DIR` etc. | host path config; script mode should use resolved `FLASHCLI_CHECKPOINT` etc., not assemble cache paths |
| other bundles' cache paths | never injected; only current preset weights |

Full ops reference: [environment.md](environment.md#bundle-entry-environment-variables-engine--script).

### 4.5 File mapping

| Manifest | File in publish package |
|----------|-------------------------|
| `"entry": { "run": { "module": "run", … } }` | `run.py` with class `RunEngine` |
| `"entry": { "serve": { "module": "serve", … } }` | `serve.py` with class `ServeEngine` |
| `"entry": { "run": { "module": "run", "attr": "main", "mode": "script" } }` | `run.py` with `main(argv)` |
| Both | **Both** `run.py` and `serve.py` are required |

---

## 5. Native `.so` layout and naming

### 5.1 Environment key (env key)

Format:

```text
{platform_tail}-{os}-{arch}-py{PY}
```

| Segment | Meaning | Example |
|---------|---------|---------|
| `platform_tail` | Opaque platform/runtime id (parsed only for matching) | `sm120-cu130` (NVIDIA); `gfx942-rocm611` (AMD ROCm) |
| `os` | Operating system | currently `linux` |
| `arch` | CPU architecture | currently `x86_64` |
| `PY` | Python ABI; must match `python_abi` | `312` → 3.12 |

NVIDIA bundles still use `sm{SM}-cu{CUDA}` as `platform_tail` (e.g. `sm89-cu124-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`). Non-NVIDIA examples: `gfx942-rocm611-linux-x86_64-py312`.

Host detection still generates NVIDIA-style keys today; override with `FLASHCLI_RUNTIME_ENV_KEY` when debugging a manifest cell that has no auto-detect yet.

### 5.2 Directory rules

1. In the **published** bundle, all native `.so` files live under `runtime/<env-key>/`, matching the manifest `runtime` map.
2. Each env key directory contains the **full** module set for that environment (see §5.3).
3. **Do not** ship `.so` files at the bundle root or under `lib/` (`lib/` is build-time staging only).
4. `flash_rt/` contains **Python source only**, no `.so`.
5. On sync, end users download **only** the one `runtime/<env-key>/` that matches their host (plus manifest and entry source tree).

### 5.3 Filename pattern

Each `.so` file:

```text
{module_base}-{flashrt_abi}-{env_key}.so
```

where `{env_key}` is the directory name (see §5.1). NVIDIA example:

```text
{module_base}-{flashrt_abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

| Part | Description |
|------|-------------|
| `module_base` | Logical pybind import name (any valid identifier segment, e.g. `flash_rt_kernels`, `flash_rt_omnivoice`) |
| `flashrt_abi` | FlashRT build id (release tag or git commit prefix; `[a-zA-Z0-9._-]` only, single segment) |
| `env_key` | Must match the parent `runtime/<env-key>/` directory |

Every tagged `{module_base}-{flashrt_abi}-{env_key}.so` in a cell directory is discovered and loaded at runtime (no manifest whitelist). If multiple ABI builds exist for the same `module_base`, the host picks one deterministically (prefer a single artifact per module when publishing).

Examples:

```text
flash_rt_kernels-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_omnivoice-1.0.0-sm120-cu130-linux-x86_64-py312.so
flash_rt_fp4-v1.2.0-sm120-cu130-linux-x86_64-py312.so
```

At load time, pybind import names remain `flash_rt_kernels`, `flash_rt_fa2`, etc. (**without** the env suffix).

### 5.4 Matrix publishing notes

- Each supported `(SM, CUDA, python_abi)` combination gets **one** env key directory.
- Env key directories in a bundle **should** expose the same `module_base` set (e.g. kernels + fa2, or kernels only).
- `python_abi` is a **single** value in the manifest; every env key’s `-py{PY}` suffix must match it.

---

## 6. Pre-publish checklist

- [ ] `format_version: 3`, `protocol_version: 1`
- [ ] `flashcli-bundle.json` at publish root
- [ ] Every `entry.*.module` has a matching `{module}.py` and class name
- [ ] Every `runtime` key has a directory with **at least one** recognizable tagged native `.so`
- [ ] No stray `.so` at bundle root or under `lib/`
- [ ] `flash_rt/` Python tree present
- [ ] With `variants`: no top-level `run_options` / `serve_options` / `weights`; each variant complete
- [ ] After FlashHub upload, `bundle.repo` returns a full `files[]` list (including `.so` `download_url`s under subdirectories)

---

## 7. Related docs

| Doc | Content |
|-----|---------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | 简体中文 |
| [model_bundle_standard.md](model_bundle_standard.md) | Catalog fields + end-user runtime flow |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
