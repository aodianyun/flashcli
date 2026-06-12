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

End users resolve bundles via `bundle.repo` in the catalog. flashcli downloads `flashcli-bundle.json` first, matches the host GPU/CUDA/Python against `runtime` env keys, then downloads only the matching `runtime/<env-key>/` tree.

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

Same repo, same **`entry`**; catalog `bundle_variant` selects weights and options from each variant block:

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

### 2.4 Catalog integration (for integrators)

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/my_model/1.0.0
  qwen3-8b-nvfp4:
    bundle_variant: qwen3          # maps to manifest variants.qwen3
    bundle:
      repo: https://flashhub…/qwen_nvfp4/1.0.1
```

- **`bundle.repo`** — FlashHub semantic version URL (not a raw zip URL).
- **`bundle_variant`** — only when the manifest defines `variants`; multiple presets may share one `repo`.

---

## 3. `flashcli-bundle.json` reference

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
| `default_variant` | recommended | Default variant name when `variants` is present |
| `post_pull` | no | Hooks after weight download (e.g. tokenizer setup) |

### 3.2 `entry`

```json
"entry": {
  "run":  { "module": "run",  "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

| Subfield | Description |
|----------|-------------|
| `module` | Python module name relative to bundle root (no `.py`), e.g. `"run"` → `run.py` |
| `attr` | Class name in that module; must implement the matching protocol (see §4) |

Capabilities are inferred from `entry`: `run` enables `flashcli run`; `serve` enables `flashcli serve`.

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
| `env` | Process env vars set at bundle activation; supports `{models_dir}`, `{bundle_root}` placeholders |
| `run_options` / `serve_options` | Variant-specific CLI options (see §3.6) |

### 3.4 `python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": [
    "numpy",
    "safetensors",
    "transformers<4.56"
  ]
}
```

| Key | Description |
|-----|-------------|
| `torch` | PyTorch wheel; `"index": "auto"` lets flashcli pick cu124/cu128 index from host CUDA (**recommended**) |
| `pip` | Additional pip packages (strings with optional version constraints) |

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
| `source` | Currently `"huggingface"` |
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

**Not declared in the manifest** (provided by flashcli): e.g. `--bundle`, `--checkpoint`, `--host`, `--port`.

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
- The bundle root is on `PYTHONPATH` at runtime; entry and co-located helpers may import each other directly.
- Entry code may depend on **`flashcli_bundle`** only (manifest, options, protocol types). **Do not** `import flashcli` (the CLI package).

Recommended imports:

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

### 4.4 File mapping

| Manifest | File in publish package |
|----------|-------------------------|
| `"entry": { "run": { "module": "run", … } }` | `run.py` with class `RunEngine` |
| `"entry": { "serve": { "module": "serve", … } }` | `serve.py` with class `ServeEngine` |
| Both | **Both** `run.py` and `serve.py` are required |

---

## 5. Native `.so` layout and naming

### 5.1 Environment key (env key)

Format:

```text
sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}
```

| Segment | Meaning | Example |
|---------|---------|---------|
| `SM` | NVIDIA compute capability × 10, no decimal | `89` → SM8.9; `120` → SM12.0 |
| `CUDA` | CUDA **user-space** version shorthand | `124` → 12.4; `130` → 13.0 |
| `os` | Operating system | currently `linux` |
| `arch` | CPU architecture | currently `x86_64` |
| `PY` | Python ABI; must match `python_abi` | `312` → 3.12 |

Examples: `sm89-cu124-linux-x86_64-py312`, `sm120-cu130-linux-x86_64-py312`.

### 5.2 Directory rules

1. In the **published** bundle, all native `.so` files live under `runtime/<env-key>/`, matching the manifest `runtime` map.
2. Each env key directory contains the **full** module set for that environment (see §5.3).
3. **Do not** ship `.so` files at the bundle root or under `lib/` (`lib/` is build-time staging only).
4. `flash_rt/` contains **Python source only**, no `.so`.
5. On sync, end users download **only** the one `runtime/<env-key>/` that matches their host (plus manifest and entry source tree).

### 5.3 Filename pattern

Each `.so` file:

```text
{module_base}-{flashrt_abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

| Part | Description |
|------|-------------|
| `module_base` | Logical module name (table below) |
| `flashrt_abi` | FlashRT build id (release tag or git commit prefix; `[a-zA-Z0-9._-]` only) |
| env suffix | Must match the directory env key (`sm`, `cu`, `os`, `arch`, `py`) |

Supported `module_base` values (longest prefix match first):

| module_base | Required |
|-------------|----------|
| `flash_rt_kernels` | **yes** |
| `flash_rt_fa2` | **yes** (FlashRT attention) |
| `flash_rt_fp4` | as needed (NVFP4 / FP4 paths) |
| `libfmha_fp16_strided` | as needed (extra FMHA in some bundles) |

Examples:

```text
flash_rt_kernels-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fp4-v1.2.0-sm120-cu130-linux-x86_64-py312.so
```

At load time, pybind import names remain `flash_rt_kernels`, `flash_rt_fa2`, etc. (**without** the env suffix).

### 5.4 Matrix publishing notes

- Each supported `(SM, CUDA, python_abi)` combination gets **one** env key directory.
- All env key directories in a bundle should expose the same set of `module_base` modules (e.g. kernels + fa2, optionally fp4).
- `python_abi` is a **single** value in the manifest; every env key’s `-py{PY}` suffix must match it.

---

## 6. Pre-publish checklist

- [ ] `format_version: 3`, `protocol_version: 1`
- [ ] `flashcli-bundle.json` at publish root
- [ ] Every `entry.*.module` has a matching `{module}.py` and class name
- [ ] Every `runtime` key has a directory with `flash_rt_kernels*.so` and `flash_rt_fa2*.so`
- [ ] No stray `.so` at bundle root or under `lib/`
- [ ] `flash_rt/` Python tree present
- [ ] With `variants`: no top-level `run_options` / `serve_options` / `weights`; each variant complete
- [ ] After FlashHub upload, `bundle.repo` returns a full `files[]` list (including `.so` `download_url`s under subdirectories)

---

## 7. Related docs

| Doc | Content |
|-----|---------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | 简体中文 |
| [model_bundle_standard.md](model_bundle_standard.md) | Complementary runtime flow summary |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
| [bundle_builder_guide.md](bundle_builder_guide.md) | Internal: build, pack, CI, flashcli commands |
