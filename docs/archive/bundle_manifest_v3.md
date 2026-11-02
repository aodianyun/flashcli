# Legacy manifest format (format_version 3)

<p align="right"><strong>English</strong> · <a href="bundle_manifest_v3.zh-CN.md">简体中文</a></p>

> **Archived reference. Not part of the current documentation index.**
>
> `format_version: 3` remains readable by the host for old FlashHub refs, but it is
> **not the format for new bundles**. New bundles must use the v4 format documented in
> [bundle_publish_standard.md](../bundle_publish_standard.md). This file records the
> legacy contract only.

## 1. Scope

A v3 bundle is a directory containing:

- `flashcli-bundle.json`
- Python entry files (`run.py` / `serve.py`) when `entry.kind` is `python`
- an optional `flash_rt/` Python tree
- `runtime/<env-key>/` native `.so` files

Native-only v3 bundles omit the Python entry and `flash_rt/`, and keep C libraries under
`runtime/<env-key>/substrate/`.

## 2. Top-level manifest

Required or contextual fields:

| Field | Meaning |
|---|---|
| `format` | `"flashcli-model-bundle"` |
| `format_version` | `3` |
| `protocol_version` | `1` |
| `name` | Descriptive bundle id |
| `description` | Optional human-readable summary |
| `entry` | `run` and/or `serve` entry specification |
| `runtime` | `env_key -> runtime/<env-key>/` map |
| `python_abi` | Required for Python entries; three digits, e.g. `"312"` |
| `python_dependencies` | Bundle venv dependencies for Python entries |
| `weights` | Main weights source for a single-preset bundle |
| `extra_weights` | Optional sidecar weight sources |
| `variants` | Optional named presets; selected with `@variant` |
| `run_options` / `serve_options` | CLI options for the corresponding capability |
| `env` | Environment variables applied before an engine entry runs |
| `post_pull` | Optional host hook after weight download |
| `runtime_abi_version` | Required by `native-abi` entries |
| `exec_protocol_version` | Required by `native-exec` entries |

### Entry

```json
"entry": {
  "run": {
    "module": "run",
    "attr": "RunEngine",
    "mode": "engine"
  },
  "serve": {
    "module": "serve",
    "attr": "ServeEngine",
    "mode": "engine"
  }
}
```

- `mode`: `engine` (default) or `script`.
- `kind`: `python` (default), `native-exec`, or `native-abi`.
- `module` / `attr`: Python module and class/callable for Python entries.

### Runtime map

```json
"runtime": {
  "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
  "sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"
}
```

Environment keys are matched against the host environment. v3 uses its legacy
version-scoped bundle/weight cache and does **not** support v4 environment fallback,
shared runtime directories, or optional runtime environments.

### Variants

v3 allowed several named presets in one repo:

```json
"variants": {
  "qwen3": {
    "weights": { "source": "huggingface", "repo": "org/qwen3" },
    "run_options": []
  },
  "qwen36": {
    "weights": { "source": "huggingface", "repo": "org/qwen36" },
    "run_options": []
  }
}
```

Users selected one with `@variant`, for example:

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
```

v4 forbids `variants`; publish separate bundles instead.

### Weights

```json
"weights": {
  "source": "modelscope",
  "repo": "org/model",
  "revision": "master"
}
```

v3 accepted branches/tags and stored weights in the version-scoped cache. v4 requires
an immutable full commit and uses the shared store keyed by source/repo/revision.

### Python dependencies

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": ["numpy", "safetensors", "transformers"]
}
```

v3 created a bundle venv from `python_abi` and these dependencies. Native-only bundles
omit both fields.

## 3. Publishing / compatibility notes

- v3 artifacts remain usable through their existing refs while the host supports them.
- Do not migrate an existing v3 ref by editing it in place; publish a new v4 bundle/ref.
- Do not add v3 fields (`variants`, top-level `runtime`, `@variant`) to new v4 bundles.
- Current authoring, runtime, and release rules: [bundle_publish_standard.md](../bundle_publish_standard.md).
