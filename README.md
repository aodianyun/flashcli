# flashcli

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Production CLI for shipping [FlashRT](https://github.com/flashrt-ai/FlashRT) inference to NVIDIA GPUs.**

One install, one preset name — flashcli resolves the right native runtime for your GPU, fetches a versioned **Model Bundle**, installs Python dependencies, caches Hugging Face weights, and runs **`run`** (engine) or **`serve`** (OpenAI-compatible HTTP) without hand-wiring FlashRT, CUDA tags, or pip matrices.

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
flashcli run pi05_libero --prompt "pick up the red block" --image /path/to/scene.jpg
```

---

## Overview

| Layer | Role |
|-------|------|
| **flashcli** | Distribution CLI — catalog, bundle fetch, env detection, deps, cache, HTTP gateway |
| **Model Bundle** | Versioned artifact (`flashcli-bundle.json` + Python entry + per-env `runtime/` on FlashHub) |
| **FlashRT** | Kernels and model frontends compiled into the bundle; not a pip dependency of flashcli |

flashcli is intentionally thin: **inference code lives in the bundle**. The CLI syncs from FlashHub, preflights the host `runtime` env, creates a bundle venv, and delegates to each bundle’s `RunEngine` / `ServeEngine`.

---

## Why flashcli

- **One command to first token** — `flashcli run <preset>` chains dependency install, FlashHub bundle sync, weight pull, and inference.
- **Split download by environment** — only this host’s `runtime/<env-key>/` is fetched; use `flashcli models envs` to see the env key.
- **Reproducible releases** — maintainers upload `dist/` to FlashHub; users pin `bundle.repo` URLs in [`models.yaml`](src/flashcli/catalog/models.yaml).
- **OpenAI-compatible serving** — Qwen NVFP4 presets expose `/v1/chat/completions`, streaming, tools, and session reuse via FlashRT `qwen36_agent`.
- **Operator-friendly** — structured serve logs, `/health` with `inference_busy`, GPU batch-1 gate (503 when busy), `doctor` for preflight checks.
- **Mirror-friendly** — Gitee install script, pip/HF mirror env vars; works in restricted networks with documented fallbacks.

---

## Supported models & hardware

| Preset | Task | GPU | CUDA line | Python | Capabilities |
|--------|------|-----|-----------|--------|--------------|
| [`pi05_libero`](bundles/pi05_libero/QUICKSTART.md) | Pi0.5 LIBERO VLA | **SM89 only** | cu124 or cu130 | **3.12** (bundle venv) | `run` |
| [`qwen3-8b-nvfp4`](bundles/qwen_nvfp4/QUICKSTART.md) | Qwen3-8B NVFP4 chat | **SM120** | **cu130 only** | **3.12** | `run`, `serve` |
| [`qwen36-27b-nvfp4`](bundles/qwen_nvfp4/QUICKSTART.md) | Qwen3.6-27B NVFP4 + MTP | **SM120** | **cu130 only** | **3.12** | `run`, `serve` |

**Platform requirements**

- Linux x86_64, NVIDIA driver with working `nvidia-smi`
- **Containers**: NVIDIA CUDA runtime images (e.g. `nvcr.io/nvidia/pytorch:25.10-py3` for Qwen SM120), not plain `python:3.x`
- **Network**: FlashHub bundle sync + Hugging Face weights on first run (Pi0.5 also needs Google Storage for PaliGemma tokenizer)

Qwen3 and Qwen3.6 share **one** FlashHub repo; catalog `bundle_variant` selects weights. Weights are **never** inside the bundle — cached under `~/.flashcli/models/<preset>/`.

---

## News

| Month | What's new |
|-------|------------|
| **2026-06** | Production-grade **Qwen3.6 chat serving** — faster real-world replies (early stop on end-of-text), true streaming, longer outputs, and a lighter install path for HTTP + inference |
| **2026-05** | **Qwen NVFP4 on Blackwell (SM120)** joins the catalog with one-command `run` and OpenAI-compatible `serve`; reproducible multi-GPU release bundles |

Full history: `git log`. Release checklist: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Getting started

### 1. Install

**Auto (recommended)**

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
```

**Github**

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
```

**From source (developers)**

```bash
git clone https://github.com/aodianyun/flashcli.git && cd flashcli
pip install -e .
```

### 2. Preflight

```bash
flashcli doctor
flashcli models list
flashcli models envs pi05_libero    # or qwen3-8b-nvfp4 / qwen36-27b-nvfp4
```

### 3. First inference — robotics (Pi0.5)

```bash
flashcli run pi05_libero \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

First run syncs the FlashHub runtime, creates the bundle venv, installs the torch stack, and pulls ~7.5GB weights.

### 4. LLM — Qwen NVFP4

**Engine (no HTTP)**

```bash
flashcli run qwen3-8b-nvfp4 --prompt "Hello" --max-tokens 128
flashcli run qwen36-27b-nvfp4 --prompt "Hello" --max-tokens 128 --K 6
```

**OpenAI-compatible server**

```bash
# qwen3-8b — short context
flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 --warmup-preset auto

# qwen3.6-27b — long context + MTP (defaults: FP8-KV, route_min_seq=0)
flashcli serve qwen36-27b-nvfp4 --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 --warmup-preset auto
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-27b-nvfp4","messages":[{"role":"user","content":"Hello"}],
       "max_tokens":512,"stream":true,"temperature":0}'
```

**Local dev bundle** (rebuilt from FlashRT, not FlashHub):

```bash
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve qwen36-27b-nvfp4 --bundle "$BUNDLE" --port 8000 --K 6 --max-seq 262208
```

Step-by-step per bundle: **[qwen_nvfp4 QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.md)** · **[pi05_libero QUICKSTART](bundles/pi05_libero/QUICKSTART.md)**

---

## Model catalog

| Preset | Weights (Hugging Face) | Bundle quickstart |
|--------|------------------------|-------------------|
| `pi05_libero` | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) | [QUICKSTART](bundles/pi05_libero/QUICKSTART.md) |
| `qwen3-8b-nvfp4` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | [QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.md) |
| `qwen36-27b-nvfp4` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) + [MTP](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) | [QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.md) |

Catalog source: [`src/flashcli/catalog/models.yaml`](src/flashcli/catalog/models.yaml). Bundle format: [docs/model_bundle_standard.md](docs/model_bundle_standard.md).

---

## CLI reference

| Command | Purpose |
|---------|---------|
| `flashcli run <preset>` | Sync inference (VLA, chat, …) |
| `flashcli serve <preset>` | OpenAI HTTP API (Qwen) |
| `flashcli pull <preset>` | Pre-fetch weights only |
| `flashcli models list` | Catalog + local cache status |
| `flashcli models envs [preset]` | Native matrix cells vs this GPU |
| `flashcli doctor [--install]` | Environment / GPU preflight |
| `flashcli bundle sync <preset>` | Pre-fetch bundle runtime from FlashHub |
| `flashcli bundle validate PATH` | Layout + native matrix check |

**Common flags**: `--bundle PATH` (local bundle root), `--no-auto-install`, `--checkpoint`, `--quiet`

`flash` and `flashcli` are equivalent entry points.

Qwen `serve` highlights: `--max-seq`, `--max-q-seq` (qwen3), `--K`, `--max-output-tokens` (default 16384), `--warmup-preset`, `--default-max-tokens`.

---

## How it works

```text
Host: install.sh → ~/.flashcli/venv (flashcli once)
  pull/sync/weights → host Python

run/serve:
  models.yaml → FlashHub → manifest + preflight → runtime/<env-key>/
  → bundle venv (python_abi, torch, …)
  → re-exec: bundle python -m flashcli.runtime.infer  (PYTHONPATH = host flashcli)
  → activate bundle → HF weights → RunEngine / ServeEngine
```

**Do not** pip-install flashcli into bundle venvs. Details: [docs/architecture.md](docs/architecture.md#host-cli-vs-bundle-infer-important).

**Local cache**

| Path | Contents |
|------|----------|
| `~/.flashcli/venv/` | Host CLI (single flashcli install) |
| `~/.flashcli/runtimes/<id>/` | Synced bundle root, `lib/`, and bundle venv |
| `~/.flashcli/models/<preset>/checkpoint/` | Model weights |
| `~/.cache/flash_rt/` | Pi0.5 PaliGemma tokenizer (post-pull) |

Legacy (safe to delete): `~/.flashcli/share/flashcli/`.

Environment variables: [docs/environment.md](docs/environment.md) (`FLASHCLI_HOME`, `HF_ENDPOINT`, `FLASHRT_QWEN36_*`, …).

---

## Documentation

| Document | Audience |
|----------|----------|
| [docs/README.md](docs/README.md) | Full doc index |
| [docs/environment.md](docs/environment.md) | Install flags, env vars, mirrors |
| [docs/runtime-matrix.md](docs/runtime-matrix.md) | Native matrix & release builds |
| [docs/model_bundle_standard.md](docs/model_bundle_standard.md) | Bundle schema (authors) |
| [docs/architecture.md](docs/architecture.md) | Modules & data flow |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribute & release checklist |
| [FlashRT](https://github.com/flashrt-ai/FlashRT) | Kernels, precision, model docs |

---

## Contributing & license

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For bundle maintainers: `bash scripts/release_bundle.sh --bundle <name> --clean`.

**License**: Apache-2.0 ([`pyproject.toml`](pyproject.toml))
