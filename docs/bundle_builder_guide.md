# Bundle build and release guide

<p align="right"><strong>English</strong> · <a href="bundle_builder_guide.zh-CN.md">简体中文</a></p>

> **Maintainer doc.** Entry point: [CONTRIBUTING.md](../CONTRIBUTING.md). External publish contract (manifest / entry / `.so` / FlashHub layout): [bundle_publish_standard.md](bundle_publish_standard.md).

For **Model Bundle maintainers**: environment setup, local dev, matrix builds, validation, FlashHub upload, and ref updates.

---

## 1. Roles

| Role | Goal | Install |
|------|------|---------|
| **Bundle builder** | Edit `run.py` / manifest, compile FlashRT, publish | `./install.sh --from-source` (Go host) + `pip install -e ./flashcli-bundle` + FlashRT + GPU |
| **End user** | `flashcli run <ref>` | `install.sh` / `auto_install.sh` (Go binary; bundle venv gets `flashcli-bundle[infer]` on demand) |

Python entry code imports **`flashcli_bundle` only** — never the `flashcli` CLI package:

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.protocol import ChatRequest, RunEngine
from flashcli_bundle.preset import Preset
```

Native-only bundles have no Python entry at all (see §5).

---

## 2. Recommended environment (mirrors)

**Hardware**

| Bundle | GPU | CUDA userland | Notes |
|--------|-----|---------------|-------|
| `pi05_libero` | SM89 (Ada), SM120 (Blackwell) | cu124 (SM89) · cu130 | SM120 uses the `sm120-cu130` cell |
| `qwen_nvfp4` | SM120 (Blackwell) | **cu130 only** | NVFP4 needs nvcc ≥ 12.8 |

**Software:** Linux x86_64 · Docker + NVIDIA Container Toolkit (matrix releases run in containers) · Go ≥ 1.24 (host) · bundle venvs pin their own `python_abi`.

**Restricted network (recommended):**

```bash
# install flashcli (Gitee + mirrors)
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
# or build from source
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --from-source

export HF_ENDPOINT=https://hf-mirror.com                 # HF weights
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/   # bundle venv pip
export PIP_TRUSTED_HOST=mirrors.aliyun.com
```

Matrix container images are declared per bundle in `release-matrix.env` (e.g. `nvcr.io/nvidia/pytorch:25.10-py3`).

---

## 3. Workspace

```text
workspace/
├── flashcli/                 # this repo
│   ├── flashcli-bundle/      # protocol + infer package
│   ├── go/                   # Go host CLI
│   ├── bundles/<name>/       # bundle sources
│   └── scripts/release_bundle.sh
└── FlashRT/                  # inference kernel (auto-cloned by release; build input only)
```

```bash
git clone https://github.com/aodianyun/flashcli.git   # or Gitee
cd flashcli
./install.sh --from-source        # Go host
pip install -e ./flashcli-bundle  # protocol (local dev/tests)
flashcli doctor
flashcli models list
```

---

## 4. Bundle directory

Python bundle (example `bundles/pi05_libero/`):

```text
pi05_libero/
├── flashcli-bundle.json      # author manifest (see §4.1)
├── run.py                    # entry.run → RunEngine
├── _pi05_compat.py           # bundle-private helper
├── flash_rt/                 # FlashRT Python tree (staged)
├── lib/                      # local build: host *.so
├── runtime/<env-key>/        # pack output: *.so (+ substrate/ for native)
├── release-matrix.env        # SM / CUDA / py ABI / pack files
├── _bundle_build.sh          # cmake + build logic
├── build.sh                  # local single-env build
├── release.sh                # → scripts/release_bundle.sh
└── dist/                     # publish tree
```

Native-only bundles (`entry.kind = native-abi|native-exec`) omit `run.py` / `flash_rt/` and place their C libraries under `runtime/<env-key>/substrate/`.

### 4.1 Manifest essentials (format_version 3)

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "pi05_libero",
  "python_abi": "312",
  "entry": { "run": { "module": "run", "attr": "RunEngine" } },
  "run_options": [ "…" ],
  "python_dependencies": { "torch": { "package": "torch", "index": "auto" } },
  "runtime": { "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312" }
}
```

- `protocol_version` must equal the installed `flashcli-bundle` `PROTOCOL_VERSION` (currently **1**).
- `run_options` / `serve_options` are the single source of CLI flags + defaults; read them via `run_option_defaults()` — never hardcode.
- With `variants`, each variant declares its own complete `run_options` / `serve_options`; no top-level duplicates.
- Native kinds add `runtime_abi_version` / `exec_protocol_version` and a `native` block (see [bundle_execution_abi.md](bundle_execution_abi.md)).

Full field reference: [bundle_publish_standard.md](bundle_publish_standard.md).

---

## 5. Local dev loop (single env, no matrix)

**Goal:** build one env's native libs on the host GPU and iterate on the entry.

**A — build native**

```bash
cd flashcli
export FLASHRT_REPO=/path/to/FlashRT   # optional; the script can clone it
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

Python bundles build FlashRT pybind extensions into `lib/` + stage `flash_rt/`.
Native bundles build the Python-free C libraries (e.g. FA2 raw → `flashrt_exec`/producer → Nexus) and stage them under `runtime/<env-key>/substrate/`.

**B — validate manifest + layout**

```bash
export BUNDLE="$(pwd)/bundles/pi05_libero"
flashcli bundle validate "$BUNDLE"
```

**C — pull weights + smoke**

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --prompt "pick up the red block" --image /path/to/base.jpg
flashcli run "$BUNDLE" --help
```

`kind=python` syncs → creates the bundle venv → installs torch + `flashcli-bundle[infer]` → re-execs the entry. `native-exec`/`native-abi` skip the venv and drive the native backend directly.

Qwen serve locally:

```bash
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
flashcli serve "$BUNDLE@qwen3" --host 127.0.0.1 --port 8000
```

---

## 6. Release pipeline

One command from the repo root:

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

Equivalent to `cd bundles/<name> && bash release.sh --clean`.

| Stage | Action | Output |
|-------|--------|--------|
| 1. Read `release-matrix.env` | SM, CUDA tags, Python ABI, Docker images, pack files | matrix dims |
| 2. Ensure FlashRT | clone/update `../FlashRT` (`FLASHRT_REPO` overrides) | source |
| 3. Docker matrix build | run `_bundle_build.sh` per CUDA line in its nvcr container | per-env native libs |
| 4. Write `runtime/` | `runtime/<env-key>/…` per env | native artifacts |
| 5. `pack.sh` | copy entry tree + native libs, refresh manifest `runtime` map | `dist/` |
| 6. Validate | ABI / layout / manifest options / protocol | exit on failure |

`--clean` removes `lib/`, `dist/`, `.build*` to avoid stale caches.

Background run + logs:

```bash
bash scripts/run_bg.sh --name release-pi05 -- bash scripts/release_bundle.sh --bundle pi05_libero --clean
bash scripts/run_bg.sh --name release-pi05 --tail
```

**Do not** ship `build.sh`, `.build*/`, or dev READMEs in `dist/` (controlled by `RELEASE_PACK_FILES`).

---

## 7. Pre-publish checklist

- [ ] `flashcli bundle validate bundles/<name>` passes
- [ ] `dist/runtime/` contains every env key declared in the manifest
- [ ] `protocol_version` matches the installed `flashcli-bundle`
- [ ] Smoke `flashcli run` / `serve` on the target GPU
- [ ] `dist/` has no dev artifacts

---

## 8. Upload to FlashHub

1. Upload the whole **`dist/`** tree to FlashHub.
2. Note the pinned ref, e.g. `flashcli-bundle/pi05_libero:1.0.4`.
3. Update the refs in the bundle `README.md` / `BUILD.md`:
   - single preset: `flashcli-bundle/pi05_libero:1.0.4`
   - multi-variant: `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3` / `@qwen36` (**`@variant` required**).
4. Users sync it with `flashcli run <ref>` or `flashcli bundle sync <ref>`.

---

## 9. Matrix summary

| | pi05_libero | qwen_nvfp4 |
|---|---|---|
| SM | 89 | 120 |
| CUDA | 124 + 130 | **130 only** |
| python_abi | 312 | 312 |
| entry | run | run + serve |
| variants | — | qwen3 / qwen36 |
| Docker cu124 | 24.05-py3 | — |
| Docker cu130 | 25.10-py3 | 25.10-py3 |

Details: [runtime-matrix.md](runtime-matrix.md).

---

## 10. Adding a new bundle

1. Copy `bundles/pi05_libero/` or `bundles/qwen_nvfp4/`.
2. Write `flashcli-bundle.json` (`protocol_version: 1`) and the entry (`run.py` / `serve.py`, or a native block).
3. Write `release-matrix.env` and `_bundle_build.sh`.
4. `build.sh` + `flashcli bundle validate` + smoke `run` / `serve`.
5. `release_bundle.sh --clean` → upload `dist/` → update pinned refs in docs.

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `protocol_version` mismatch | update the host `pip install -e ./flashcli-bundle`; manifest `protocol_version: 1` |
| run still uses an old bundle | compare `runtime_id`/`repo` in output with `flashcli doctor`; `flashcli bundle sync <ref> --force` |
| bundle venv missing `flashcli_bundle` | delete `~/.flashcli/runtimes/<id>/` and rerun; or trigger a rebuild |
| bundle venv missing `flashcli-bundle` | set `FLASHCLI_BUNDLE_PIP_SPEC=/path/to/flashcli-bundle[infer]` or `~/.flashcli/install.env` `FLASHCLI_INSTALL_REPO/REF`; never `pip install flashcli` |
| HF weight download fails | `export HF_ENDPOINT=https://hf-mirror.com` then `flashcli pull` |
| `NativeEnvironmentNotSupportedError` | ensure the manifest has this host's env key; `flashcli bundle sync <ref> --force` |
| qwen build fails on cu124 | qwen is cu130-only; use the 25.10-py3 container |

---

## 12. Related docs

| Doc | Contents |
|-----|----------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | **External** publish contract: manifest, entry, `.so`, FlashHub layout |
| [bundle_execution_abi.md](bundle_execution_abi.md) | `entry.kind` backends + native contracts |
| [model_bundle_standard.md](model_bundle_standard.md) | preset ref syntax + runtime flow |
| [architecture.md](architecture.md) | host CLI vs bundle venv |
| [environment.md](environment.md) | environment variables |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | PR / git rules |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | protocol package API |
