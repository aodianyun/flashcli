# wan22 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：暂存 FlashRT Python + Wan 包 + 带标签 `.so`，打包、校验、冒烟 `run`、发布。

**要求：** Linux · NVIDIA SM120 · CUDA 13 用户态 · FlashRT 源码（可编译 `.so`）· Wan2.2 官方检出（含 `wan/` 包）· flashcli 开发安装。

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/wan22"
export FLASHRT_REPO=/path/to/FlashRT
export WAN_ROOT=/path/to/Wan2.2
```

本 bundle 使用 **Python 3.10**（`python_abi: "310"`）。native `.so` 须与 py310 匹配。

## 1. 构建

`build.sh` 暂存最小化 `flash_rt/`（与 `.so` 版本锁定）、vendor Wan 的 `wan/` 包（t2v 子集），并将带标签的 kernels 放入 `runtime/<env-key>/`。

```bash
bash bundles/wan22/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --wan-root "$WAN_ROOT"
```

可选参数：`--env-key`、`--flashrt-abi`、`--python-minor`。SM/CUDA 由 `nvidia-smi` / `nvcc` 自动探测。主机存在 gcc-11 时强制作为 nvcc 宿主编译器（产出兼容 glibc 2.35 的 `.so`）。

产出：`flash_rt/`、`wan/`、`runtime/sm120-cu130-linux-x86_64-py310/*.so`、`flash_rt/BUNDLE_VERSION`

## 2. 打包

```bash
bash bundles/wan22/pack.sh
export BUNDLE="$(pwd)/bundles/wan22/dist"
```

`pack.sh` → `scripts/pack_bundle.sh`。上传树含 `flashcli-bundle.json`、`run.py`、`flash_rt/`、`wan/`、`runtime/<env-key>/`（见 `release-matrix.env` 的 `RELEASE_PACK_FILES`）。

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. 冒烟测试

权重来自 ModelScope（`Wan-AI/Wan2.2-TI2V-5B`，约 34 GB）。`pull` 之后推理始终 `HF_HUB_OFFLINE=1`。

```bash
flashcli pull "$BUNDLE"

# 最快端到端检查（依赖已缓存时，空闲 GPU 约 20–40 秒）：
PYTHONUNBUFFERED=1 flashcli run "$BUNDLE" \
  --frames 5 --steps 2 --out smoke.mp4

# 5060 Ti 基线（832×480，81 帧，20 步）：
flashcli run "$BUNDLE"

# 图像生成视频：
flashcli run "$BUNDLE" \
  --mode i2v --image /path/start.png --frames 81
```

## 5. 发布

将 `dist/` 上传 FlashHub，ref 如 `flashcli-bundle/wan22:1.0.0`（按实际版本号调整）。

多环境矩阵（Docker）：

```bash
bash scripts/release_bundle.sh --bundle wan22 --clean
```

`release-matrix.env` 固定 SM120 / cu130 / py310；`_bundle_build.sh` 实现矩阵单元格 + 收尾钩子（见 `scripts/lib/bundle_hooks.sh`）。

## 说明

- **不修改 FlashRT / Wan 源码**：原样拷贝。缺少 `flash_attn` 时，由 `run.py` 在运行时将 vendored Wan 注意力重绑定到 SDPA 回退。
- **版本锁定**：同一次构建从同一 FlashRT commit 暂存 `flash_rt/` 与 `.so`（`flash_rt/BUNDLE_VERSION`）。
- **权重**：不在 zip 内；由 `pull` 从 ModelScope 拉取。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `NativeEnvironmentNotSupportedError` | 为本机 env key 重编；`flashcli models envs "$BUNDLE"` |
| `no kernel image...` | GPU/CUDA 与 manifest `runtime` 不匹配 |
| Wan 根目录无效 | `--wan-root` 须指向含 `wan/` 包的检出 |
| 权重下载失败 | 检查 ModelScope 访问；或预置 checkpoint |
| ≤16 GB OOM | 保持 `--offload-model true`；降低 `--width` / `--height` / `--frames` |
| `frames` 被拒绝 | 须满足 `4n+1` |
