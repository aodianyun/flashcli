# Bundle build and release guide

<p align="right"><strong>English</strong> · <a href="bundle_builder_guide.zh-CN.md">简体中文</a></p>

> **Internal maintainer doc** — not listed in public README / `docs/README.md`. Entry point: [CONTRIBUTING.md](../CONTRIBUTING.md).

For **Model Bundle maintainers (internal)**: environment setup, local dev, matrix builds, validation, FlashHub upload, and catalog updates.

**External bundle publish standard** (manifest / entry / `.so` / FlashHub layout; no scripts) → **[bundle_publish_standard.md](bundle_publish_standard.md)**

Format summary: [model_bundle_standard.md](model_bundle_standard.md) (catalog + runtime flow). End-user commands: each bundle’s `QUICKSTART.md`.

> **Full step-by-step guide:** [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) (中文). This page is an English summary.

---

## 1. Roles

| Role | Goal | Install |
|------|------|---------|
| **Bundle builder** | Edit `run.py` / manifest, compile FlashRT, publish | `pip install -e ./flashcli-bundle -e .` + FlashRT + Docker/GPU |
| **End user** | `flashcli run <preset>` | `install.sh` / `auto_install.sh` (git: flashcli-bundle + flashcli) |

Entry modules import **`flashcli_bundle` only** — not the full `flashcli` CLI package.

---

## 2. Recommended environment (mirrors)

**Restricted network (recommended):**

```bash
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
export HF_ENDPOINT=https://hf-mirror.com
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
export PIP_TRUSTED_HOST=mirrors.aliyun.com
```

| Bundle | GPU | CUDA |
|--------|-----|------|
| `pi05_libero` | SM89 only | cu124 or cu130 |
| `qwen_nvfp4` | SM120 | cu130 only |

---

## 3. Workspace

```bash
git clone https://github.com/aodianyun/flashcli.git
cd flashcli
pip install -e ./flashcli-bundle
pip install -e .
flashcli doctor
```

Layout: `flashcli/` + sibling `FlashRT/` (auto-cloned by release script).

---

## 4. Local dev loop

```bash
export BUNDLE="$(pwd)/bundles/pi05_libero"
export FLASHRT_REPO=/path/to/FlashRT
export HF_ENDPOINT=https://hf-mirror.com

bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
flashcli bundle validate "$BUNDLE"
flashcli pull pi05_libero --bundle "$BUNDLE"
flashcli run pi05_libero --bundle "$BUNDLE" --image /path/to.jpg
flashcli run pi05_libero --help
```

---

## 5. Release pipeline

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

| Stage | Purpose |
|-------|---------|
| Read `release-matrix.env` | SM × CUDA × py312 matrix |
| FlashRT clone/build | Native `.so` per env |
| `runtime/<env-key>/` | Split native artifacts under `dist/` |
| `pack_bundle.sh` | Bundle source tree + refreshed manifest |
| Validate | layout, options, `protocol_version` |

Output: `bundles/<name>/dist/` → upload tree to FlashHub → set `models.yaml` → `bundle.repo`.

Background run:

```bash
bash scripts/run_bg.sh --name release-pi05 -- \
  bash scripts/release_bundle.sh --bundle pi05_libero --clean
bash scripts/run_bg.sh --name release-pi05 --tail
```

---

## 6. Manifest essentials

Required: `format_version: 3`, **`protocol_version: 1`**, `python_abi: "312"`, `run_options`/`serve_options`, `torch.index: "auto"`.

Field reference: [bundle_publish_standard.md](bundle_publish_standard.md). Step-by-step (Chinese): [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md).

---

## 7. Pre-publish checklist

- [ ] `flashcli bundle validate bundles/<name>` passes
- [ ] `dist/runtime/` contains all env keys in manifest
- [ ] `protocol_version` matches installed `flashcli-bundle`
- [ ] Smoke `flashcli run` / `serve` on target GPU
- [ ] Upload `dist/` to FlashHub; update `bundle.repo` in `models.yaml`

Example repo URL:

```text
https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.3
```

---

## 8. Related docs

- [bundle_publish_standard.md](bundle_publish_standard.md) — external publish standard (manifest, entry, `.so`, FlashHub)
- [runtime-matrix.md](runtime-matrix.md) — matrix details  
- [architecture.md](architecture.md) — host CLI vs bundle venv  
- [flashcli-bundle/README.md](../flashcli-bundle/README.md) — protocol package  
