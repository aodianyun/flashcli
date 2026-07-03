# qwen_nvfp4 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. 编译 native

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen_nvfp4/${ENV_KEY}"
cp bundles/qwen_nvfp4/lib/*.so "bundles/qwen_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

缺少 `runtime/<env-key>/flash_rt_kernels*.so` 会在加载时报 `ImportError: flash_rt_kernels`。

## 2. 打包 / 发布

```bash
bash bundles/qwen_nvfp4/pack.sh
# 或一键发布构建：
bash bundles/qwen_nvfp4/release.sh --clean
export BUNDLE="$(pwd)/bundles/qwen_nvfp4/dist"
```

## 3. 拉取权重

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull "$BUNDLE@qwen3"
flashcli pull "$BUNDLE@qwen36"
```

## 4. 冒烟 — run

```bash
flashcli run "$BUNDLE@qwen3" --prompt "你好" --max-tokens 64
flashcli run "$BUNDLE@qwen36" --prompt "你好" --max-tokens 64 --K 6
```

## 5. 冒烟 — serve

```bash
flashcli serve "$BUNDLE@qwen3" --host 127.0.0.1 --port 8000

curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3","messages":[{"role":"user","content":"你好"}],"max_tokens":64,"stream":true}'

curl -s http://127.0.0.1:8000/health | jq
```

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `ImportError: flash_rt_kernels` | 将 `lib/*.so` 复制到 `runtime/<env-key>/` |
| FlashHub runtime 过旧 | 本地重编；使用 `bundles/qwen_nvfp4@qwen36` 路径 |
| `max_tokens must be <= N` | 提高 qwen36 serve 的 `--max-output-tokens` |
