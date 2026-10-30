# higgs_audio — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：staging FlashRT py310 native + 最小 `flash_rt/`、打包、校验并冒烟 `run`。

**要求：** Linux · NVIDIA SM120 · CUDA 13.x · 为 Python 3.10 构建的 FlashRT 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
./install.sh --from-source
pip install -e ./flashcli-bundle
export FLASHRT_REPO=/path/to/FlashRT
export BUNDLE="$(pwd)/bundles/higgs_audio"
```

## 1. 编译

```bash
bash bundles/higgs_audio/build.sh --repo-root "$FLASHRT_REPO"
```

产物：`runtime/sm120-cu130-linux-x86_64-py310/*.so`、`flash_rt/`。构建只 staging 已有的 py310 产物，不编译 FlashRT。

## 2. 打包

```bash
bash bundles/higgs_audio/pack.sh --repo-root "$FLASHRT_REPO"
export BUNDLE="$(pwd)/bundles/higgs_audio/dist"
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
flashcli run "$BUNDLE" --text "Hello world" --out /tmp/higgs.wav
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 为 `flashcli-bundle/higgs_audio:1.0.1`（按实际版本号调整）。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| 缺 py310 native | 用 Python 3.10 构建 FlashRT，再重跑 `build.sh` |
| `NativeEnvironmentNotSupportedError` | 重建 SM120/cu130/py310 单元 |
| torchaudio 加载失败 | bundle 会 stub 不可用的 torchaudio；用当前 `env_guard.py` 重新构建/打包 |
