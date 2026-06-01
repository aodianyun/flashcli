# pi05_libero quick start

<p align="right"><a href="QUICKSTART.zh-CN.md">简体中文</a></p>

**Requires**: Linux · NVIDIA GPU (**SM89** / **SM120**) · Python **3.10–3.12**  
**Preset**: `pi05_libero` · weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) (~7.5GB, not in zip)

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/pi05_libero"   # local dev; omit for CDN zip
```

Check runtime cell for this host:

```bash
flashcli models envs pi05_libero
# SM120 must match *-cu130-* (not cu124)
```

---

## 1. Build local bundle (dev)

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
flashcli bundle validate "$BUNDLE"
```

SM89-only FA2 speedup (**not for release**):

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" --fa2-native-only
```

---

## 2. Pull weights / run

```bash
export HF_ENDPOINT=https://hf-mirror.com   # if needed

flashcli pull pi05_libero --bundle "$BUNDLE"

flashcli run pi05_libero --bundle "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

Weights cache: `~/.flashcli/models/pi05_libero/checkpoint/`

Use a local checkpoint:

```bash
flashcli run pi05_libero --bundle "$BUNDLE" \
  --checkpoint /path/to/checkpoint \
  --image /path/to/base.jpg
```

---

## 3. Benchmark

```bash
flashcli run pi05_libero --bundle "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg \
  --benchmark 5
```

---

## 4. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `LocalEntryNotFoundError` | network/DNS; set `HF_ENDPOINT` or `--checkpoint` |
| `no kernel image...` on SM120 | match `sm120-cu130-*`; rebuild bundle |
| `'GemmRunner'... fp8_nt_dev` | rebuild FlashRT or use `_pi05_compat.py` |
| `FvkContext is already registered` | upgrade flashcli |

Release: `bash scripts/release_bundle.sh --bundle pi05_libero --clean` → upload zip → update `models.yaml`.
