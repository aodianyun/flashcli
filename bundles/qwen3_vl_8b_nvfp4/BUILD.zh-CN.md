# qwen3_vl_8b_nvfp4 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：构建 FlashRT py312 native、打包 v4 bundle、校验并冒烟 `run` / `serve`。

**要求：** Linux · NVIDIA SM120 · CUDA 13.x · 含 Qwen3-VL kernels 的 FlashRT 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/qwen3_vl_8b_nvfp4"
```

## 1. 编译

```bash
bash bundles/qwen3_vl_8b_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

选中的 runtime 单元需要 `flash_rt_qwen3_vl_kernels*.so`。

## 2. 打包

```bash
bash bundles/qwen3_vl_8b_nvfp4/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/qwen3_vl_8b_nvfp4/dist"
```

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. 冒烟测试

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --image /path/to/scene.jpg --prompt "Describe this image." --max-pixels 100000 --max-seq 1024 --max-q-seq 256
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000 --max-pixels 100000 --max-seq 1024
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 为 `flashcli-bundle/qwen3_vl_8b_nvfp4:1.0.0`（按实际版本号调整）。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| 缺 `flash_rt_qwen3_vl_kernels` | 用 `-DFLASHRT_BUILD_QWEN3_VL=ON` 重建 |
| BF16 checkpoint 报错 | 使用 FlashRT NVFP4 checkpoint |
| 16GB OOM | 降低 `--max-pixels` / `--max-seq` |
| 缺 `Qwen3VLProcessor` | bundle 需要 `transformers>=4.57.0` |
