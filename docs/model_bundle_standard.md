# flashcli Model Bundle standard

<p align="right"><strong>English</strong> · <a href="model_bundle_standard.zh-CN.md">简体中文</a></p>

Third parties ship models as a **Model Bundle**: bundled **runtime**, **partner inference entry**, and weight metadata. flashcli **only** loads the bundle and calls `entry`; it does **not** implement Run/Serve logic in flashcli source.

Maintainers: see [DEVELOPER.md](../codeplan/DEVELOPER.md). The **public catalog** is currently **[`pi05_libero`](../models/models.yaml) only**; other `bundles/` drafts must not be added to `models.yaml` until validated.

Bundle sources are declared in **`models.yaml`**: single-env top-level **`bundle.zip` / `path` / `git`**, or multi-env **`bundle.variants.<sm*-cu*-os-arch>`**. Git repos or zip archives may also contain inner **`variants/<sm-cu-os-arch>/`** (one source, many envs — subfolder chosen by GPU after unpack/clone).

## Directory layout

`{bundle_root}` is the bundle root (git variant dir, `--bundle`, or `~/.flashcli/bundles/...` cache):

```text
{bundle_root}/
├── flashcli-bundle.json       # required: manifest, weights, entry
├── partner/                   # recommended: entry source (build copies to runtime/python/partner/)
│   ├── run.py                 # RunEngine
│   └── serve_*.py             # ServeEngine
├── checkpoint/                # optional: embedded weights
└── runtime/
    ├── manifest.json          # Python deps, CUDA metadata
    ├── lib/                   # when native_runtime: *.so
    └── python/                # added to PYTHONPATH
        ├── partner/           # entry modules (import partner.run, etc.)
        └── flash_rt/          # optional: FlashRT tree + linked .so
```

### Two runtime types

| Type | `native_runtime` | Contents |
|------|------------------|----------|
| **FlashRT bundle** | `true` (default) | `lib/*.so` + `python/flash_rt` + `partner/` |
| **Python-only bundle** | `false` | `manifest.json` + `python/partner/` only (for extension; repo example bundles are FlashRT bundles) |

On activate, flashcli adds `runtime/python` to `PYTHONPATH`; if only `bundle_root/partner/` exists, it links or copies into `runtime/python/partner/`.

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
  "format_version": 1,
  "name": "my-model",
  "description": "optional",
  "native_runtime": true,
  "runtime_dir": "runtime",
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
    "run": {
      "module": "partner.run",
      "attr": "RunEngine"
    },
    "serve": {
      "module": "partner.serve",
      "attr": "ServeEngine"
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `native_runtime` | When `false`, `lib/flash_rt_kernels.so` is not required |
| `runtime_dir` | Default `runtime` |
| `capabilities` | `run`, `serve` |
| `entry.run` / `entry.serve` | Module + class name under **`partner`** |
| `weights` / `extra_weights` | Primary / additional weight downloads |
| `defaults` / `serve` | Default args passed to engines (read by partner) |
| `post_pull` | Steps after weight pull (tokenizer, etc.) |
| `requires.sm` | Optional: variant selection hint |
| `git_ref` / `native_libs` | Written by build scripts (release snapshot metadata) |

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
  "entry": {
    "run": {
      "module": "partner.run",
      "attr": "RunEngine"
    }
  }
}
```

The catalog points at assembled runtimes via `models.yaml` `bundle.variants` (or top-level `bundle.zip`); weights come from HF. Building from source: [bundles/pi05_libero/README.md](../bundles/pi05_libero/README.md). Users can run `flashcli models envs <preset>` to see whether this machine matches a configured environment.

### Example: LLM + `serve` (internal draft, not published)

Qwen NVFP4 bundles use `capabilities: ["run", "serve"]` and `requires.sm: ["120"]`; build with `scripts/build_qwen_bundle.sh` on SM120. **Do not add to catalog until validated.**

## `partner/` entry contract

- Module paths are relative to `runtime/python` (e.g. `partner.run` → `runtime/python/partner/run.py`).
- Classes implement `RunEngine` / `ServeEngine` from flashcli [`engines/base.py`](../src/flashcli/engines/base.py).
- May use `from flashcli.bundle.activate import active_bundle` to read `defaults` / `serve` from `flashcli-bundle.json`.
- All inference logic (NVFP4/VLA, transformers, etc.) stays **inside partner**.

During development, keep `partner/` at `bundle_root/partner/`; `build_*_bundle.sh` rsyncs to `runtime/python/partner/`.

## `runtime/manifest.json`

Generated at build time by `scripts/generate_runtime_manifest.py`, or hand-written for Python-only bundles, e.g.:

```json
{
  "format": "flashrt-runtime-manifest",
  "format_version": 1,
  "python_dependencies": {
    "torch": "torch",
    "pip": ["numpy", "transformers<4.56", "safetensors"],
    "optional_groups": { "server": ["fastapi", "uvicorn"] }
  },
  "cuda": {
    "cuda_tag": "124",
    "recommended_torch_index": "cu124"
  }
}
```

When `native_runtime: true`, `lib/*.so` are linked into `runtime/python/flash_rt/` on activate.

## flashcli inference protocol (host side)

`partner` inside the bundle implements these interfaces; flashcli `serve` exposes fixed HTTP routes.

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

## Git multi-environment repo

```text
flashcli-bundle-my-model/
├── variants/
│   ├── sm89-cu124-linux-x86_64/
│   │   ├── flashcli-bundle.json
│   │   └── runtime/
│   └── sm120-cu128-linux-x86_64/
└── README.md
```

Directory name: `sm{SM}-cu{CUDA_TAG}-{os}-{arch}`.

**Version = git ref** (branch / tag); do not use `variants/env/1.0.0/` subdirs.

Ref priority: `--bundle-ref` > `bundle.git.ref` > `refs[].default` > `main`.

### Local cache

```text
~/.flashcli/bundles/<preset>/refs/<sanitized_ref>/
~/.flashcli/bundles/<preset>/.flashcli_bundle.json
```

Weights are separate: `~/.flashcli/models/<preset>/checkpoint/`.

## `models/models.yaml`

**Only** preset names and bundle sources. Two layouts:

### Single bundle (compatible)

Top-level `zip` / `path` / `git` for all environments. If the zip/git tree contains `variants/<sm-cu-os-arch>/`, flashcli still picks the subfolder by GPU after unpack/clone.

### Multi-environment catalog (`bundle.variants`)

Per-machine `zip` / `path` / `git` under keys `sm{SM}-cu{CUDA_TAG}-{os}-{arch}`. Missing keys produce an error listing configured environments. Use `flashcli models envs [preset]`.

| Field | Description |
|-------|-------------|
| `bundle.path` | Local bundle (may contain inner `variants/`) |
| `bundle.git` | Remote repo + default ref |
| `bundle.zip` | Remote URL or local `.zip` |
| `bundle.variants` | Per-environment `zip` / `path` / `git` overrides |
| `bundle.refs` | Optional git ref allowlist |

Bundle resolution: `--bundle` > **catalog source for GPU** > cache > zip or git > (single artifact) inner `variants/`.

## Build scripts (FlashRT source tree, Linux GPU)

```bash
# Pi0.5: compile flash_rt_kernels + pack partner/
bash flashcli/scripts/build_pi05_bundle.sh \
  --bundle-dir flashcli/bundles/pi05_libero

# Repack only (existing .so)
bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir ... --pack-only

# Embed weights
bash flashcli/scripts/build_pi05_bundle.sh \
  --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
```

Internal Qwen drafts use `scripts/build_qwen_bundle.sh` (**SM120**); do not add to catalog until validated. See [bundles/README.md](../bundles/README.md).

## Minimum delivery checklist

1. `flashcli-bundle.json` (with `entry` → `partner.*`)
2. `runtime/manifest.json`
3. `runtime/python/partner/` (`RunEngine` / `ServeEngine`)
4. If `native_runtime`: `runtime/lib/*.so` + `runtime/python/flash_rt/`
5. Weights: `checkpoint/` or `weights.repo`

## Validation

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
# serve bundles after validation:
# flashcli bundle install /path/to/bundle --profile serve
# flashcli serve <preset> --bundle /path/to/bundle --port 8000
```
