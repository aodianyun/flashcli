# qwen3_vl_nvfp4 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. 编译 native

```bash
bash bundles/qwen3_vl_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/qwen3_vl_nvfp4/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/qwen3_vl_nvfp4/${ENV_KEY}"
cp bundles/qwen3_vl_nvfp4/lib/*.so "bundles/qwen3_vl_nvfp4/${ENV_KEY}/"
flashcli bundle validate "$BUNDLE"
```

runtime 目录需包含 `flash_rt_qwen3_vl_kernels*.so`。

## 2. 权重（维护者）

运行时需要 **FlashRT NVFP4** checkpoint（非 BF16 原版权重）：

```bash
bash bundles/qwen3_vl_nvfp4/scripts/prepare_qwen3_vl_weights.sh \
  --flashrt-repo "$FLASHRT_REPO" \
  --dst /tmp/Qwen3-VL-8B-FlashRT-NVFP4

# 开发嵌入：
bash bundles/qwen3_vl_nvfp4/build.sh --embed-checkpoint /tmp/Qwen3-VL-8B-FlashRT-NVFP4
```

上传 HF 后更新 manifest 中 `weights.repo`，再：

```bash
bash bundles/qwen3_vl_nvfp4/pack.sh
export BUNDLE="$(pwd)/bundles/qwen3_vl_nvfp4/dist"
flashcli pull "$BUNDLE"
```

## 3. 冒烟 — run

```bash
flashcli run "$BUNDLE" \
  --image /path/to/scene.jpg \
  --prompt "描述这张图。" \
  --max-tokens 64
```

## 4. 冒烟 — serve

```bash
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000 --warmup-preset short

curl -s http://127.0.0.1:8000/health | jq
```

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `flash_rt_qwen3_vl_kernels is not built` | 用 `build.sh` 重编（已开 `-DFLASHRT_BUILD_QWEN3_VL=ON`） |
| BF16 checkpoint 报错 | 用 `prepare_qwen3_vl_weights.sh` 量化 |
| 16 GB OOM | 降低 `--max-pixels`、`--max-seq` |
| 缺少 `Qwen3VLProcessor` | bundle 需 `transformers>=4.57.0` |
