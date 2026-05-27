# qwen_nvfp4

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

> **Internal draft.** One SM120 runtime artifact; multiple catalog presets select weights via `bundle_variant`.

## Pattern

One `bundle.zip` (or `bundle.path`) + `variants` in `flashcli-bundle.json` + multiple `models.yaml` presets sharing that bundle. See [README.zh-CN.md](README.zh-CN.md).

## Build & run

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 6
```
