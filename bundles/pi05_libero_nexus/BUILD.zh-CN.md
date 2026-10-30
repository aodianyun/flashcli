# pi05_libero_nexus — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：构建 FlashRT-Nexus native substrate、打包 v4 native-abi bundle、校验并冒烟 `run` / `serve`。

**要求：** Linux · NVIDIA SM120 · CUDA 13.x · FlashRT 源码 · FlashRT-Nexus 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
./install.sh --from-source
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_SRC=/path/to/FlashRT-Nexus
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
```

## 1. 编译

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_SRC" \
  -j "$(nproc)"
```

产物：`runtime/sm120-cu130-linux-x86_64/{substrate,bin,calib}/`、`.build/manifest-overlay.json`。

## 2. 打包

```bash
bash bundles/pi05_libero_nexus/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus/dist"
```

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
flashcli models show "$BUNDLE"
```

## 4. 冒烟测试

```bash
export HF_ENDPOINT=https://hf-mirror.com
flashcli pull "$BUNDLE"
flashcli run "$BUNDLE" --prompt "pick up the red block and place it in the tray" --image /path/v0.jpg,/path/v1.jpg
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8080
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 为 `flashcli-bundle/pi05_libero_nexus:1.0.3`（按实际版本号调整）。exec 示例不会被打包或发布。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| 缺少 Nexus 源码 | 传 `--nexus-src` 或设置 `NEXUS_SRC` |
| `NativeEnvironmentNotSupportedError` | 重建 SM120/cu130 native-abi 单元 |
| 权重下载失败 | 设置 `HF_ENDPOINT` 或使用 `flashcli pull` |
