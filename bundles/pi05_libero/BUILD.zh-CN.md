# pi05_libero — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：编译 FlashRT native、放入 `runtime/<env-key>/`、校验、冒烟 `run`。

**要求：** Linux · NVIDIA SM89 或 SM120 · 对应 CUDA 用户态 · FlashRT 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/pi05_libero"
export FLASHRT_REPO=/path/to/FlashRT
```

## 1. 编译 native

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/pi05_libero/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/pi05_libero/${ENV_KEY}"
cp bundles/pi05_libero/lib/*.so "bundles/pi05_libero/${ENV_KEY}/"
```

仅 SM89 的 FA2 加速（仅开发，勿用于发布）：

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" --fa2-native-only
```

## 2. 打包（可选，生成 `dist/`）

```bash
bash bundles/pi05_libero/pack.sh
export BUNDLE="$(pwd)/bundles/pi05_libero/dist"
```

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. 冒烟测试

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg

flashcli run "$BUNDLE" \
  --image /path/to/base.jpg \
  --benchmark 5
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 如 `flashcli-bundle/pi05_libero:1.0.4`（按实际版本号调整）。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `NativeEnvironmentNotSupportedError` | 为本机 env key 重编；`flashcli models envs "$BUNDLE"` |
| `no kernel image...` | GPU/CUDA 与 manifest `runtime` 不匹配 |
| `'GemmRunner'... fp8_nt_dev` | 重编 FlashRT 或使用 `_pi05_compat.py` |
| 权重下载失败 | `HF_ENDPOINT` 或预下载后 `--checkpoint` |
