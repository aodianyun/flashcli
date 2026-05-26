# flashcli Model Bundle standard

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

Third parties ship models as a **Model Bundle**: one **`flashcli-bundle.json`**, **`entry` inference modules**, and optional **FlashRT `.so` / `flash_rt` Python**. flashcli **only** loads the bundle and calls `entry`; it does **not** implement Run/Serve logic in flashcli source.

Maintainers: see [DEVELOPER.md](../codeplan/DEVELOPER.md). The **public catalog** is currently **[`pi05_libero`](../src/flashcli/catalog/models.yaml) only**; other `bundles/` drafts must not be added to `models.yaml` until validated.

Each preset has **one** bundle source in **`models.yaml`**: top-level **`bundle.zip` / `path` / `git`**. Multi-environment runtimes ship inside that artifact (recommended: **`lib/` native matrix** in a single zip). See [runtime-matrix.md](runtime-matrix.md) for `pi05_libero` release layout.

## Directory layout

`{bundle_root}` is the bundle root (git checkout, `--bundle`, or `~/.flashcli/bundles/...` cache). **No fixed subdirectories** beyond `flashcli-bundle.json` and the Python modules referenced by `entry`.

```text
{bundle_root}/
├── flashcli-bundle.json    # required: entry, weights, python_dependencies, optional native_matrix
├── run.py                  # example: entry.run.module = "run"
├── lib/                    # optional (recommended): tagged *.so for multi-env matrix
├── flash_rt/               # optional: FlashRT Python tree (official bundles; no duplicate .so inside)
└── checkpoint/             # optional: embedded weights
```

**Published reference (`pi05_libero`)** — single CDN zip with a `lib/` matrix plus:

```text
flashcli-bundle.json
run.py
_pi05_compat.py
flash_rt/
lib/
  flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py310.so
  flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py310.so
  ... (cu130, py311, py312, …)
```

**Third-party bundles** may ship only `run.py` plus explicit `modules[].file` paths, or a full `lib/` matrix; publish each `.so` once and declare paths in the manifest.

On activate, flashcli prepends **`bundle_root`** to `PYTHONPATH`, installs `python_dependencies`, and loads native code from `lib/` (matrix) or `modules[]` (flat paths).

## Weights

Declared in `flashcli-bundle.json` (not in `models.yaml`):

1. **In-bundle**: `{bundle_root}/checkpoint/` (`weights_dir` can rename this folder)
2. **HuggingFace**: `weights.repo` / `revision`

Resolution order:

1. `--checkpoint`
2. Existing files under in-bundle `{weights_dir}/`
3. `~/.flashcli/models/<preset>/checkpoint/`
4. Download from HuggingFace per `weights`

## `flashcli-bundle.json`

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 2,
  "name": "my-model",
  "description": "optional",
  "weights_dir": "checkpoint",
  "capabilities": ["run", "serve"],
  "weights": {
    "source": "huggingface",
    "repo": "org/weights",
    "revision": "main"
  },
  "defaults": {},
  "serve": {},
  "post_pull": [{ "tokenizer": "paligemma" }],
  "entry": {
    "run": { "module": "run", "attr": "RunEngine" },
    "serve": { "module": "serve", "attr": "ServeEngine" }
  },
  "python": ">=3.10,<3.13",
  "python_abi": "310",
  "python_dependencies": {
    "torch": "torch",
    "pip": ["numpy", "transformers<4.56", "safetensors"],
    "optional_groups": { "server": ["fastapi", "uvicorn"] }
  },
  "cuda": {
    "cuda_tag": "124",
    "recommended_torch_index": "cu124"
  },
  "native_layout": "matrix",
  "native_matrix": ["sm89-cu124-linux-x86_64-py310"],
  "modules": [
    { "file": "flash_rt_kernels.so", "optional": false }
  ]
}
```

| Field | Description |
|-------|-------------|
| `format_version` | Must be `2` (flat bundle root) |
| `capabilities` | `run`, `serve` |
| `entry.run` / `entry.serve` | Module + class name relative to **bundle root** on `PYTHONPATH` |
| `python_dependencies` | pip / torch |
| `python` / `python_abi` | Interpreter constraints; mismatch fails fast at activate |
| `cuda` | `cuda_tag`, `recommended_torch_index`, etc. |
| `native_layout` / `native_matrix` | When `native_layout` is `matrix`, flashcli picks tagged `.so` under `lib/` for this host |
| `modules` | Optional explicit `.so` paths relative to bundle root; used when there is no `lib/` matrix |
| `weights` / `extra_weights` | Primary / additional weight downloads |
| `defaults` / `serve` | Default args passed to engines (read by partner code) |
| `post_pull` | Steps after weight pull (tokenizer, etc.) |
| `requires.sm` | Optional GPU SM allowlist checked at native load |
| `build` / `native_libs` | Snapshot metadata written by build scripts |

### Native `.so` naming (`lib/` matrix)

Tagged artifacts use:

```text
{module}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

Example: `flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

At `flashcli run`, the host key is **`sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`** (includes Python ABI). CUDA tags may fuzzy-match within the same major runtime family (e.g. `cu124`↔`cu128`, not `cu124`→`cu130`). Details: [runtime-matrix.md](runtime-matrix.md).

### Example: Pi0.5 VLA (published — `pi05_libero`)

```json
{
  "name": "pi05_libero",
  "config": "pi05",
  "framework": "torch",
  "capabilities": ["run"],
  "requires": { "sm": ["89", "120"] },
  "weights": {
    "source": "huggingface",
    "repo": "lerobot/pi05_libero_finetuned_v044",
    "revision": "main"
  },
  "post_pull": [{ "tokenizer": "paligemma" }],
  "entry": { "run": { "module": "run", "attr": "RunEngine" } },
  "python_dependencies": { "torch": "torch", "pip": ["numpy", "pillow", "..."] }
}
```

The catalog points at one assembled zip via `models.yaml` → `bundle.zip`; weights come from HF. Building from source: [bundles/pi05_libero/README.md](../bundles/pi05_libero/README.md). Run `flashcli models envs pi05_libero` to see this machine’s runtime key and whether `lib/` contains a matching artifact.

### Example: LLM + `serve` (internal draft, not published)

Qwen NVFP4 bundles use `capabilities: ["run", "serve"]` and `requires.sm: ["120"]`; build with `scripts/build_qwen_bundle.sh` on SM120. **Do not add to catalog until validated.**

## `entry` contract

- `entry.*.module` is relative to the **bundle root** (e.g. `run` → `run.py`).
- Classes implement `RunEngine` / `ServeEngine` from flashcli [`engines/base.py`](../src/flashcli/engines/base.py).
- May use `from flashcli.bundle.activate import active_bundle` to read `defaults` / `serve` from `flashcli-bundle.json`.
- All inference logic (`flash_rt`, `transformers`, bare `.so` ops, etc.) stays **inside the entry module**.

## flashcli inference protocol (host side)

Bundle `entry` modules implement these interfaces; flashcli `serve` exposes fixed HTTP routes.

### RunEngine

| Method | Description |
|--------|-------------|
| `load(checkpoint, preset, **opts)` | Load model |
| `predict(prompt=, images=, **kwargs)` | Returns `ndarray` or `dict` |

### ServeEngine

| Method | Description |
|--------|-------------|
| `load(...)` | Load model |
| `warmup(spec)` | Optional, e.g. `"32:128,128:256"` |
| `model_id` | Id returned by `/v1/models` |
| `chat(request)` | Non-streaming |
| `chat_stream(request)` | Streaming |

## Git bundles

**Version = git ref** (branch / tag / commit). One ref → one checkout under:

```text
~/.flashcli/bundles/<preset>/refs/<sanitized_ref>/
~/.flashcli/bundles/<preset>/.flashcli_bundle.json
```

Ref priority: `--bundle-ref` > `bundle.git.ref` > `refs[].default` > `main`.

flashcli locates `flashcli-bundle.json` at the repo root or the first valid subtree; **native environment selection happens at runtime** from `lib/` or `modules[]`, not from a `variants/` subdirectory in git.

Weights are separate: `~/.flashcli/models/<preset>/checkpoint/`.

## `src/flashcli/catalog/models.yaml`

**Only** preset names and **one** bundle source per preset (`schema_version: 6` today).

```yaml
schema_version: 6

models:
  pi05_libero:
    description: Pi0.5 LIBERO — ...
    bundle:
      zip: https://cdn.example/.../flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
      # path: bundles/pi05_libero   # local debug (needs lib/*.so for this host)
      # git: { repo: "...", ref: main }
```

| Field | Description |
|-------|-------------|
| `bundle.path` | Local bundle directory (relative to flashcli package root) |
| `bundle.git` | Remote repo + default ref |
| `bundle.zip` | Remote URL or local `.zip` |
| `bundle.refs` | Optional git ref allowlist |

**`bundle.variants` is removed** — do not register per-environment zip URLs in the catalog. Ship multiple environments inside one zip’s `lib/` matrix instead ([runtime-matrix.md](runtime-matrix.md)).

Bundle resolution: `--bundle` > catalog `zip` / `path` / `git` > local cache > download / clone.

Environment variables (`FLASHCLI_MODELS_YAML`, `FLASHCLI_HOME`, `HF_ENDPOINT`, …): [environment.md](environment.md).

## Build scripts (FlashRT source tree, Linux GPU)

**Matrix release (recommended for `pi05_libero`):**

```bash
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → bundles/pi05_libero/dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
```

**Single-environment bundle (maintainer dev):**

```bash
bash scripts/build_pi05_bundle.sh --bundle-dir flashcli/bundles/pi05_libero
bash scripts/build_pi05_bundle.sh --bundle-dir ... --pack-only   # reuse cached .so
bash scripts/build_pi05_bundle.sh \
  --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
```

Internal Qwen drafts use `scripts/build_qwen_bundle.sh` (**SM120**); do not add to catalog until validated. See [bundles/README.md](../bundles/README.md).

## Minimum delivery checklist

1. `flashcli-bundle.json` (`format_version: 2`, with `entry`, `python_dependencies`, optional `native_layout` / `modules` / `cuda`)
2. Python module(s) for `entry` (e.g. `run.py` + `RunEngine`)
3. Optional: `lib/` tagged `.so` matrix **or** `modules[].file` list
4. Optional: `flash_rt/` Python tree
5. Weights: `checkpoint/` or `weights.repo`

## Validation

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
# serve bundles after validation:
# flashcli bundle install /path/to/bundle --profile serve
# flashcli serve <preset> --bundle /path/to/bundle --port 8000
```
