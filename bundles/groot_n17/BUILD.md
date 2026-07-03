# groot_n17 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT
```

This bundle uses **Python 3.10** (`python_abi: "310"`). FlashRT native `.so` files must be built for **py310** to match the bundle venv.

**You do not need to install Python 3.10 manually.** `build.sh` reads `python_abi` from `flashcli-bundle.json`, finds a matching interpreter, and auto-installs one (standalone tarball or apt) when missing. Override with `FLASHCLI_PY310_BIN` or `--python-bin`; disable auto-install with `--no-install-python` or `FLASHCLI_AUTO_INSTALL_BUILD_PYTHON=0`.

## 1. Build

`build.sh` vendors Isaac-GR00T inference code into `gr00t/` at the bundle root (no `pip install gr00t`). `activate_bundle` prepends the bundle root to `PYTHONPATH`, so preprocessing and FlashRT `denormalize_action` share the same vendored tree.

```bash
bash bundles/groot_n17/build.sh \
  --repo-root "$FLASHRT_REPO" \
  -j "$(nproc)"
```

CMake passes `-DFA2_HDIMS="64;96;128" -DFA2_DTYPES="fp16;bf16"`. N1.7 needs **64** for the VLM backbone (ViT + VL self-attn FA2) and **96;128** for DiT attention.

Outputs: `gr00t/` (vendored), `runtime/sm120-cu130-linux-x86_64-py310/*.so`, `flash_rt/`, `.build/manifest-overlay.json`

Skip cmake if FlashRT is already built:

```bash
bash bundles/groot_n17/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --pack-only
```

Re-vendor only (no FlashRT rebuild):

```bash
bash bundles/groot_n17/vendor_gr00t.sh
python3 bundles/groot_n17/_verify_gr00t_vendor.py
```

## 2. Pack

```bash
bash bundles/groot_n17/pack.sh
export BUNDLE="$(pwd)/bundles/groot_n17/dist"
```

`pack.sh` copies `gr00t/` into `dist/` (`RELEASE_PACK_FILES` in `release-matrix.env`). If `flashcli run` reports `No module named 'gr00t'`, the deployed bundle lacks vendored `gr00t/` — re-run `build.sh` then `pack.sh`, or `flashcli bundle validate "$BUNDLE"`.

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. Smoke test

`flashcli pull` downloads GR00T N1.7 weights only (no extra tokenizer).

```bash
export HF_ENDPOINT=https://hf-mirror.com   # if needed

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "put the blue block in the green bowl" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --image /path/v0.jpg,/path/v1.jpg

flashcli run "$BUNDLE" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2

flashcli run "$BUNDLE" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --benchmark 5
```

After upgrading the bundle manifest or vendored `gr00t/`, recreate the runtime venv:

```bash
rm -rf ~/.flashcli/runtimes/groot_n17-local-*/venv
flashcli run "$BUNDLE" ...
```

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `GemmRunner missing fp8_nt_dev` | Rebuild FlashRT or use `_groot_compat.py` shim |
| `vendor-gr00t` clone fails | Set `FLASHCLI_GIT_PROXY` or `FLASHCLI_GR00T_SRC=/path/to/Isaac-GR00T` |
| Vendored gr00t layout incomplete | Re-run `vendor_gr00t.sh`; check `_verify_gr00t_vendor.py` output |
| Python ABI mismatch on `.so` | Re-run `build.sh` (no `--pack-only`) so py310 native build runs |
| `No Python py310 found` with auto-install off | Omit `--no-install-python`, or set `FLASHCLI_PY310_BIN` |
| Nonsense actions | Wrong `embodiment_tag` or `--num-views`; use real images when possible |
| CUDA OOM during run | Preprocess releases Gr00tPolicy before FlashRT load; close other GPU jobs |

### Vendored gr00t (Isaac-GR00T)

N1.7 does **not** `pip install` Isaac-GR00T. Instead:

1. `vendor_gr00t.sh` shallow-clones ref `ab88b50...` (no simulation submodules) into `bundles/groot_n17/gr00t/`
2. `gr00t/VENDOR.json` records repo, ref, and commit for traceability
3. Runtime pip deps (`torch==2.7.1`, `transformers==4.57.3`, `tyro`, …) come only from `flashcli-bundle.json`; see `gr00t-inference-requirements.txt` for vendored-gr00t extras

GitHub unreachable:

```bash
export FLASHCLI_GIT_PROXY=https://mirror.ghproxy.com/
# or point at a local/offline checkout:
export FLASHCLI_GR00T_SRC=/path/to/Isaac-GR00T
bash bundles/groot_n17/vendor_gr00t.sh
```

Source cache: `~/.flashcli/cache/isaac-gr00t-src/<git-ref>/` (skipped when `FLASHCLI_GR00T_SRC` is set).

To bump the upstream pin, update `GR00T_REF` in `vendor_gr00t.sh`, re-vendor, re-run `_verify_gr00t_vendor.py`, and rebuild/pack.
