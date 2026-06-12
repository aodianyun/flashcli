# Bundle build and release guide

<p align="right"><strong>English</strong> · <a href="bundle_builder_guide.zh-CN.md">简体中文</a></p>

For **Model Bundle maintainers (internal)**: environment setup, local dev, matrix builds, validation, FlashHub upload, and catalog updates.

**External bundle publish standard** (manifest / entry / `.so` / FlashHub layout; no scripts) → **[bundle_publish_standard.md](bundle_publish_standard.md)**

Format summary: [model_bundle_standard.md](model_bundle_standard.md). End-user commands: each bundle’s `QUICKSTART.md`.

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
| `runtime/<env-key>/` | Split native artifacts |
| `pack_bundle.sh` | `dist/` source tree + refreshed manifest |
| Validate | layout, options, `protocol_version` |
| Zip | Upload to FlashHub |

Output: `bundles/<name>/dist/` → upload → set `models.yaml` → `bundle.repo`.

---

## 6. Manifest essentials

Required: `format_version: 3`, **`protocol_version: 1`**, `python_abi: "312"`, `run_options`/`serve_options`, `torch.index: "auto"`.

See [model_bundle_standard.md](model_bundle_standard.md) and the [Chinese guide](bundle_builder_guide.zh-CN.md) for the full step-by-step walkthrough.

---

## 7. Related docs

- [bundle_publish_standard.md](bundle_publish_standard.md) — external publish standard (manifest, entry, `.so`, FlashHub)
- [runtime-matrix.md](runtime-matrix.md) — matrix details  
- [architecture.md](architecture.md) — host CLI vs bundle venv  
- [flashcli-bundle/README.md](../flashcli-bundle/README.md) — protocol package  
