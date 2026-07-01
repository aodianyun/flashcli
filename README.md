# flashcli

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Production CLI for shipping [FlashRT](https://github.com/flashrt-project/FlashRT) inference.**

One install, one preset name — flashcli resolves the right native runtime for your GPU, fetches a versioned **Model Bundle**, installs Python dependencies, caches Hugging Face weights, and runs **`run`** (engine) or **`serve`** (OpenAI-compatible HTTP) without hand-wiring FlashRT, CUDA tags, or pip matrices.

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
flashcli run flashcli-bundle/pi05_libero:1.0.4
```

---

## Overview

| Layer | Role |
|-------|------|
| **flashcli** | Distribution CLI — preset refs, bundle fetch, env detection, deps, cache, HTTP gateway |
| **Model Bundle** | Versioned artifact (`flashcli-bundle.json` + Python entry + per-env `runtime/` on FlashHub) |
| **FlashRT** | Kernels and model frontends compiled into the bundle; not a pip dependency of flashcli |

flashcli is intentionally thin: **inference code lives in the bundle**. The CLI syncs from FlashHub, preflights the host `runtime` env, creates a bundle venv, and delegates to each bundle’s `RunEngine` / `ServeEngine`.

---

## Why flashcli

- **One command to first token** — `flashcli run <ref>` chains dependency install, FlashHub bundle sync, weight pull, and inference.
- **Split download by environment** — only this host’s `runtime/<env-key>/` is fetched; use `flashcli models envs` to see the env key.
- **Reproducible releases** — maintainers upload `dist/` to FlashHub; users pin refs such as `flashcli-bundle/pi05_libero:1.0.4`.
- **OpenAI-compatible serving** — Qwen NVFP4 presets expose `/v1/chat/completions`, streaming, tools, and session reuse via FlashRT `qwen36_agent`.
- **Operator-friendly** — structured serve logs, `/health` with `inference_busy`, GPU batch-1 gate (503 when busy), `doctor` for preflight checks.
- **Mirror-friendly** — Gitee install script, pip/HF mirror env vars; works in restricted networks with documented fallbacks.

---

## Supported models & hardware

Browse published bundles on **[FlashHub](https://flashhub.top)**. The table below lists common presets (hardware matrix); per-bundle steps are in each bundle’s QUICKSTART.

| Ref | Task | GPU | CUDA line | Python | Capabilities |
|-----|------|-----|-----------|--------|--------------|
| [`flashcli-bundle/pi05_libero:1.0.4`](bundles/pi05_libero/QUICKSTART.md) | Pi0.5 LIBERO VLA | **SM89**, **SM120** | cu124 (SM89) · cu130 | **3.12** (bundle venv) | `run` |
| [`flashcli-bundle/qwen_nvfp4:1.0.1@qwen3`](bundles/qwen_nvfp4/QUICKSTART.md) | Qwen3-8B NVFP4 chat | **SM120** | **cu130 only** | **3.12** | `run`, `serve` |
| [`flashcli-bundle/qwen_nvfp4:1.0.1@qwen36`](bundles/qwen_nvfp4/QUICKSTART.md) | Qwen3.6-27B NVFP4 + MTP | **SM120** | **cu130 only** | **3.12** | `run`, `serve` |
| [`flashcli-bundle/qwen3_vl_nvfp4:1.0.0`](bundles/qwen3_vl_nvfp4/QUICKSTART.md) | Qwen3-VL-8B NVFP4 image+text | **SM120** | **cu130 only** | **3.12** | `run`, `serve` |
| [`bundles/groot_n16`](bundles/groot_n16/QUICKSTART.md) *(local dev)* | GROOT N1.6 VLA | **SM120** | **cu130 only** | **3.12** | `run` |

Full repo index: [bundles/README.md](bundles/README.md). Published refs: [FlashHub](https://flashhub.top).

**Platform requirements**

- Linux x86_64, NVIDIA driver with working `nvidia-smi`
- **Containers**: NVIDIA CUDA runtime images (e.g. `nvcr.io/nvidia/pytorch:25.10-py3` for Qwen SM120), not plain `python:3.x`
- **Network**: FlashHub bundle sync + Hugging Face weights on first run (Pi0.5 also needs Google Storage for PaliGemma tokenizer)

Qwen3 and Qwen3.6 share **one** FlashHub repo; `@qwen3` / `@qwen36` in the ref selects weights. Weights are **never** inside the bundle — cached under `~/.flashcli/models/<bundle>/<version>@<variant>/`.

---

## News

| Month | What's new |
|-------|------------|
| **2026-06** | Production-grade **Qwen3.6 chat serving** — faster real-world replies (early stop on end-of-text), true streaming, longer outputs, and a lighter install path for HTTP + inference |
| **2026-05** | **Qwen NVFP4 on Blackwell (SM120)** on FlashHub — one-command `run` and OpenAI-compatible `serve`; reproducible multi-env release bundles |

Full history: `git log`.

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
pip install -e ./flashcli-bundle -e .
```

### 2. Preflight

```bash
flashcli doctor
flashcli models list
flashcli models envs flashcli-bundle/pi05_libero:1.0.4
```

### 3. First inference — robotics (Pi0.5)

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

First run syncs the FlashHub runtime, creates the bundle venv, installs the torch stack, and pulls ~7.5GB weights.

### 4. LLM — Qwen NVFP4

**Engine (no HTTP)**

```bash
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --prompt "Hello" --max-tokens 128
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --prompt "Hello" --max-tokens 128 --K 6
flashcli run flashcli-bundle/qwen3_vl_nvfp4:1.0.0 \
  --image /path/to/scene.jpg --prompt "Describe this image." --max-tokens 128
```

**OpenAI-compatible server**

```bash
# qwen3 — short context
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen3 --host 0.0.0.0 --port 8000 \
  --max-seq 2048 --max-q-seq 1024 --warmup-preset auto

# qwen36 — long context + MTP (defaults: FP8-KV, route_min_seq=0)
flashcli serve flashcli-bundle/qwen_nvfp4:1.0.1@qwen36 --host 0.0.0.0 --port 8000 \
  --K 6 --max-seq 262208 --warmup-preset auto

# qwen3-vl — multimodal (image + text)
flashcli serve flashcli-bundle/qwen3_vl_nvfp4:1.0.0 --host 0.0.0.0 --port 8000 \
  --max-pixels 500000 --warmup-preset short
```

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen36","messages":[{"role":"user","content":"Hello"}],
       "max_tokens":512,"stream":true,"temperature":0}'
```

**Local dev bundle** (rebuilt from FlashRT, not FlashHub):

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve bundles/qwen_nvfp4@qwen36 --port 8000 --K 6 --max-seq 262208
```

Step-by-step per bundle: **[qwen_nvfp4 QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.md)** · **[qwen3_vl_nvfp4 QUICKSTART](bundles/qwen3_vl_nvfp4/QUICKSTART.md)** · **[pi05_libero QUICKSTART](bundles/pi05_libero/QUICKSTART.md)** · **[groot_n16 QUICKSTART](bundles/groot_n16/QUICKSTART.md)** *(local dev)*

---

## CLI reference

| Command | Purpose |
|---------|---------|
| `flashcli run <ref>` | Sync inference (VLA, chat, …) |
| `flashcli serve <ref>` | OpenAI HTTP API (Qwen) |
| `flashcli pull <ref>` | Pre-fetch runtime + weights (same download path as first `run`) |
| `flashcli models list` | Locally cached refs + weight status (discover bundles on [FlashHub](https://flashhub.top)) |
| `flashcli models envs [ref]` | Native matrix cells vs this GPU |
| `flashcli doctor [--install]` | Environment / GPU preflight |
| `flashcli bundle sync <ref>` | Pre-fetch bundle runtime from FlashHub |
| `flashcli bundle validate PATH` | Layout + native matrix check |

**Common flags**: `--no-auto-install`, `--checkpoint`, `--quiet`  
**Ref syntax**: FlashHub `flashcli-bundle/name:version[@variant]` or local `bundles/name[@variant]` (directory must contain `flashcli-bundle.json`). Multi-variant bundles require `@variant`. Details: [model_bundle_standard.md](docs/model_bundle_standard.md).

Qwen `serve` highlights: `--max-seq`, `--max-q-seq` (qwen3), `--K`, `--max-output-tokens` (default 16384), `--warmup-preset`, `--default-max-tokens`.

---

## How it works

```text
Host: install.sh → ~/.flashcli/venv (flashcli once)
  pull / run preflight → host Python (sync, weights, extra_weights, post_pull)

run/serve:
  ref → FlashHub → manifest + preflight → runtime/<env-key>/
  → ensure weights on host (download if missing; same as pull)
  → bundle venv (python_abi, torch, …)
  → re-exec: bundle python -m flashcli_bundle.infer  (HF hub offline)
  → activate bundle → local checkpoint → RunEngine / ServeEngine / script main
```

**Do not** pip-install flashcli into bundle venvs. Details: [docs/architecture.md](docs/architecture.md#host-cli-vs-bundle-infer-important).

**Local cache**

| Path | Contents |
|------|----------|
| `~/.flashcli/venv/` | Host CLI (single flashcli install) |
| `~/.flashcli/runtimes/<id>/` | Synced bundle root (`runtime/<env-key>/`, entry tree), bundle venv |
| `~/.flashcli/models/<bundle>/<version>@<variant>/checkpoint/` | Model weights |
| `~/.cache/flash_rt/` | Pi0.5 PaliGemma tokenizer (post-pull) |

Environment variables: [docs/environment.md](docs/environment.md) (`FLASHCLI_HOME`, `HF_ENDPOINT`, `FLASHRT_QWEN36_*`, …).

---

## Documentation

| Role | Read in order |
|------|----------------|
| **End user** | This README → [pi05_libero QUICKSTART](bundles/pi05_libero/QUICKSTART.md) or [qwen_nvfp4 QUICKSTART](bundles/qwen_nvfp4/QUICKSTART.md) → [environment.md](docs/environment.md) |
| **Integrator** | [FlashHub](https://flashhub.top) → [model_bundle_standard.md](docs/model_bundle_standard.md) — preset ref syntax |
| **Bundle author** | [bundle_publish_standard.md](docs/bundle_publish_standard.md) → [flashcli-bundle/README.md](flashcli-bundle/README.md) |

How host CLI, bundle venv, and FlashHub sync work: [architecture.md](docs/architecture.md). Full index: [docs/README.md](docs/README.md).

---

## Contributing & license

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

**License**: Apache-2.0 ([`pyproject.toml`](pyproject.toml))
