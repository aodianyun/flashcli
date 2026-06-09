# pi05_libero 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA GPU（**仅 SM89**，如 RTX 4090 / 4060 Ti Ada）· Python **3.10–3.12**  
**Preset**：`pi05_libero` · 权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)（~7.5GB，不进 zip）

> **SM120 / Blackwell**（如 RTX 5090、PRO 5000）**暂不支持**。SM120 请用 [`qwen_nvfp4`](../qwen_nvfp4/QUICKSTART.zh-CN.md) 系列 preset。

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/pi05_libero"   # 本地 dev；省略则走 FlashHub sync
```

检查本机匹配哪档 runtime：

```bash
flashcli models envs pi05_libero
# 期望 sm89-cu124-* 或 sm89-cu130-*（与本机 CUDA 用户态一致）
```

---

## 1. 本地 bundle 编译（dev）

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
flashcli bundle validate "$BUNDLE"
```

仅本机 SM89 加速 FA2（**不可用于发布**）：

```bash
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" --fa2-native-only
```

---

## 2. 拉权重 / 运行

```bash
# 内网镜像
export HF_ENDPOINT=https://hf-mirror.com

flashcli pull pi05_libero --bundle "$BUNDLE"

flashcli run pi05_libero --bundle "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg
```

权重缓存：`~/.flashcli/models/pi05_libero/checkpoint/`

指定已有 checkpoint：

```bash
flashcli run pi05_libero --bundle "$BUNDLE" \
  --checkpoint /path/to/checkpoint \
  --image /path/to/base.jpg
```

---

## 3. 性能抽测

```bash
flashcli run pi05_libero --bundle "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/to/base.jpg \
  --benchmark 5
```

---

## 4. 常见问题

| 现象 | 处理 |
|------|------|
| `LocalEntryNotFoundError` | 网络/DNS；设 `HF_ENDPOINT`，或预下载后 `--checkpoint` |
| `NativeEnvironmentNotSupportedError` / SM120 | pi05 **仅 SM89**；换 Ada 显卡，或 Blackwell 上用 Qwen |
| `no kernel image...` | GPU/CUDA 格不匹配；在 SM89 上执行 `flashcli models envs pi05_libero` |
| `'GemmRunner'... fp8_nt_dev` | 更新 FlashRT 并重编，或 bundle 内 `_pi05_compat.py` shim |
| `FvkContext is already registered` | 升级 flashcli |

维护者发布：

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --clean
# → 上传 dist/ 到 FlashHub → 更新 models.yaml 中 pi05_libero.bundle.repo
```
