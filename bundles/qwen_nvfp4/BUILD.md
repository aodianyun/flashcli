# qwen_nvfp4 — build & smoke test

<p align="right"><strong>English</strong> · <a href="BUILD.zh-CN.md">简体中文</a></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. Build natives

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen_nvfp4/${ENV_KEY}"
cp bundles/qwen_nvfp4/lib/*.so "bundles/qwen_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

Missing `runtime/<env-key>/flash_rt_kernels*.so` → `ImportError: flash_rt_kernels` at load time.

## 2. Pack / release

```bash
bash bundles/qwen_nvfp4/pack.sh
# or one-shot FlashHub build:
bash bundles/qwen_nvfp4/release.sh --clean
export BUNDLE="$(pwd)/bundles/qwen_nvfp4/dist"
```

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
| `ImportError: flash_rt_kernels` | Copy `lib/*.so` into `runtime/<env-key>/` |
| Stale FlashHub runtime | Rebuild locally; use `bundles/qwen_nvfp4@qwen36` path |
| `max_tokens must be <= N` | Raise `--max-output-tokens` (qwen36 serve) |
