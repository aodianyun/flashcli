# flashcli

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Production CLI for shipping [FlashRT](https://github.com/flashrt-project/FlashRT) inference.**

One install, one preset name — flashcli resolves the right native runtime for your GPU, fetches a versioned **Model Bundle** from FlashHub, installs its Python dependencies, caches weights, and runs **`run`** (inference) or **`serve`** (OpenAI-compatible HTTP) without hand-wiring FlashRT, CUDA tags, or pip matrices.

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
flashcli doctor
flashcli run flashcli-bundle/<name>:<version>[@variant]
```

---

## Bundles

All supported models and hardware live on **[FlashHub](https://flashhub.top)** — browse there and use the ref shown on each bundle page. GPU/CUDA/Python requirements, capabilities, and the `run` / `serve` commands and options are documented on the bundle page and its `README.md` (index: [bundles/](bundles/README.md)).

Ref syntax: `flashcli-bundle/<name>:<version>[@variant]` (FlashHub) or `bundles/<name>[@variant]` (local dev; the directory must contain `flashcli-bundle.json`). Multi-variant bundles require `@variant`. Details: [model_bundle_standard.md](docs/model_bundle_standard.md). Run `flashcli --help` for the full command list.

---

## News

| Month | What's new |
|-------|------------|
| **2026-10** | **Go-only host** — one static binary (the Python host is gone); **native-exec** / **native-abi** backends run bundles **without Python**; the synced bundle tree and weights cache are **shared across `@variant`** |
| **2026-06** | Production-grade **Qwen3.6 chat serving** — faster real-world replies (early stop on end-of-text), true streaming, longer outputs, and a lighter install path for HTTP + inference |
| **2026-05** | **Qwen NVFP4 on Blackwell (SM120)** on FlashHub — one-command `run` and OpenAI-compatible `serve`; reproducible multi-env release bundles |

Full history: `git log`.

---

## Getting started

### Install the host (`flashcli`)

**One-click (recommended)**

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
# CN mirror: curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
```

`install.sh` installs the `flashcli` binary: by default it downloads
`flashcli-<os>-<arch>` + `sha256sums.txt` from the latest release (no Go needed),
verifies sha256, and writes `~/.flashcli/install.env`. Pass `--from-source` to
clone or update the checkout under `~/.flashcli/src` (override with
`--source-dir` / `FLASHCLI_CLONE_DIR`) and build with Go instead. Missing system
tools (curl/wget, sha256, git) are auto-installed via the OS package manager
when running as root. `~/.flashcli` is runtime data; a source checkout is a
build input.

**Auto (picks GitHub/Gitee by reachability)**

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
```

**From source (developers)**

```bash
git clone https://github.com/aodianyun/flashcli.git && cd flashcli
bash scripts/build_go.sh        # builds go/ → dist/go/flashcli-<os>-<arch>
```

The host is a static Go binary (no Python host). Bundle venvs still get
`flashcli-bundle[infer]` on demand (source: [flashcli-bundle/](flashcli-bundle/)).

### Preflight

```bash
flashcli doctor
flashcli models envs flashcli-bundle/<name>:<version>   # native matrix vs this GPU
```

### Run and serve

```bash
flashcli run   flashcli-bundle/<name>:<version>[@variant] [OPTIONS]        # inference
flashcli serve flashcli-bundle/<name>:<version>[@variant] --port 8000      # OpenAI-compatible HTTP

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<variant>","messages":[{"role":"user","content":"Hello"}],"max_tokens":512,"stream":true}'
```

First run syncs the FlashHub runtime, creates the bundle venv, installs the torch stack, and pulls weights. The host records the expected weight file set before downloading, resumes interrupted downloads, and verifies it offline on later runs. Model-specific flags, defaults, and examples are in each bundle [README](bundles/README.md).

**Local dev bundle** (rebuilt from FlashRT, not FlashHub):

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli serve bundles/qwen_nvfp4@qwen36 --port 8000 --K 6
```

---

## Documentation

| Role | Read in order |
|------|----------------|
| **End user** | This README (install + run) → bundle [README](bundles/README.md) → [environment.md](docs/environment.md) |
| **Integrator** | [FlashHub](https://flashhub.top) → [model_bundle_standard.md](docs/model_bundle_standard.md) — preset ref syntax |
| **Bundle author** | [bundle_publish_standard.md](docs/bundle_publish_standard.md) → [flashcli-bundle/README.md](flashcli-bundle/README.md) |

How the host, bundle venv, and FlashHub sync work: [architecture.md](docs/architecture.md). Full index: [docs/README.md](docs/README.md).

---

## Contributing & license

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

**License**: Apache-2.0 ([`pyproject.toml`](pyproject.toml))
