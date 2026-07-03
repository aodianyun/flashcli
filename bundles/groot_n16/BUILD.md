# groot_n16 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. Build

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

Outputs: `runtime/sm120-cu130-linux-x86_64-py312/*.so`, `flash_rt/`, `.build/manifest-overlay.json`

Skip cmake if FlashRT is already built:

```bash
bash bundles/groot_n16/build.sh --repo-root "$FLASHRT_REPO" --pack-only
```

## 2. Pack

```bash
bash bundles/groot_n16/pack.sh
export BUNDLE="$(pwd)/bundles/groot_n16/dist"
```

## 3. Validate

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. Smoke test

`flashcli pull` downloads GR00T weights + Qwen3 tokenizer (`checkpoint/tokenizer/`).

```bash
export HF_ENDPOINT=https://hf-mirror.com   # if needed

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the cup on the table" \
  --embodiment-tag gr1 \
  --num-views 1 \
  --image /path/to/rgb.jpg

flashcli run "$BUNDLE" --embodiment-tag gr1 --num-views 1

flashcli run "$BUNDLE" --embodiment-tag gr1 --num-views 1 --benchmark 5
```

Confirm tokenizer:

```bash
ls "$(flashcli models show "$BUNDLE" 2>/dev/null | sed -n 's/.*checkpoint: //p')/tokenizer/"
```

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `GemmRunner missing fp8_nt_dev` | Rebuild FlashRT or use `_groot_compat.py` shim |
| Tokenizer load fails | Re-run `flashcli pull`; need 4 files under `checkpoint/tokenizer/` |
| Noisy actions | Wrong `embodiment_tag` or `--num-views` |
