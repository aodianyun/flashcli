# qwen_nvfp4 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT   # same commit as flash_rt/BUNDLE_VERSION / published build.git_commit
```

## 1. Build natives

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

Produces:

| Path | Purpose |
|------|---------|
| `flash_rt/` | FlashRT Python (same commit as `.so`) |
| `flash_rt/BUNDLE_VERSION` | FlashRT commit / abi lock |
| `lib/*.so` | Matrix staging |
| `runtime/<env-key>/*.so` | Host load path (e.g. `sm121-cu130-linux-aarch64-py312`) |
| `.build/manifest-overlay.json` | `build.git_commit` + scanned `runtime` map |

Supports host-detected SM (e.g. **SM120**, **SM121**/GB10); NVFP4 usually lives in `flash_rt_kernels` (standalone `flash_rt_fp4` optional). Unsupported arches fail in FlashRT CMake, not via an SM allowlist.

## 2. Pack (runnable `dist/`)

```bash
bash bundles/qwen_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
# or one-shot FlashHub matrix build:
bash bundles/qwen_nvfp4/release.sh --clean

export BUNDLE="$(pwd)/bundles/qwen_nvfp4/dist"
flashcli bundle validate "$BUNDLE"
```

`pack.sh` (vs bare `pack_bundle.sh`):

- Mirrors `lib/` → `runtime/<env-key>/` when needed
- Ensures `flash_rt/BUNDLE_VERSION`
- Auto `--skip-matrix-verify` when host cells ≠ `release-matrix.env` (e.g. SM121 / aarch64)
- Merges overlay into `dist/flashcli-bundle.json` so **`dist/` is runnable**
- Checks kernels + version lock after pack

Use **`dist/`** for `pull` / `run` / `serve` (author `flashcli-bundle.json` may only list the official SM120×x86_64 cell).

## 3. Pull weights

```bash
export HF_ENDPOINT=https://hf-mirror.com   # if needed

flashcli pull "$BUNDLE@qwen3"
flashcli pull "$BUNDLE@qwen36"
```

## 4. Smoke test — run

```bash
flashcli run "$BUNDLE@qwen3" --prompt "Hello" --max-tokens 64
flashcli run "$BUNDLE@qwen36" --prompt "Hello" --max-tokens 64 --K 6
```

## 5. Smoke test — serve

```bash
flashcli serve "$BUNDLE@qwen3" --host 127.0.0.1 --port 8000

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3","messages":[{"role":"user","content":"Hello"}],"max_tokens":64,"stream":true}'

curl -s http://127.0.0.1:8000/health | jq
```

## Troubleshooting (build)

| Symptom | Fix |
|---------|-----|
| `flash_rt_fp4 … missing (sm != 120)` | Stale script; current build treats `flash_rt_fp4` as optional |
| `ImportError: flash_rt_kernels` | Re-run `build.sh` / `pack.sh`; confirm `dist/runtime/<env-key>/` |
| `Missing flash_rt/` on pack | `build.sh` must finish (stages `flash_rt/` + `BUNDLE_VERSION`) |
| FlashRT version skew | Match `flash_rt/BUNDLE_VERSION` ↔ `build.git_commit` ↔ FlashRT checkout |
| Stale FlashHub runtime | Rebuild locally; serve `bundles/qwen_nvfp4/dist@qwen36` |
| `max_tokens must be <= N` | Raise `--max-output-tokens` (qwen36 serve) |
