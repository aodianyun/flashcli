# pi05_libero 快速上手

<p align="right"><a href="QUICKSTART.md">English</a></p>

**环境**：Linux · NVIDIA **SM89**（Ada）或 **SM120**（Blackwell）· CUDA **12.4+**（SM89）或 **13.x**（SM120）· Python **3.12**（bundle venv；主机 CLI 3.10+）  
**Preset**：`pi05_libero` · 权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)（~7.5GB，不进 zip）

```bash
cd /path/to/flashcli
pip install -e .
export BUNDLE="$(pwd)/bundles/pi05_libero"   # 本地 dev；省略则走 FlashHub sync
```

检查本机匹配哪档 runtime：

```bash
flashcli models envs pi05_libero
# 期望 sm89-cu124-*、sm89-cu130-* 或 sm120-cu130-*（与本机 GPU + CUDA 用户态一致）
```

---

## 1. 本地 bundle 编译（dev）

`build.sh` 先将 `.so` 产出到 `lib/`；validate/run 前需复制到 manifest 里对应的 `runtime/<env-key>/`：

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
ENV_KEY="$(python3 -c "import json; print(next(iter(json.load(open('bundles/pi05_libero/flashcli-bundle.json'))['runtime'])))")"
mkdir -p "bundles/pi05_libero/${ENV_KEY}"
cp bundles/pi05_libero/lib/*.so "bundles/pi05_libero/${ENV_KEY}/"
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

# bundle 参数见 manifest run_options；默认值在 flashcli-bundle.json
flashcli run pi05_libero --help

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
| `NativeEnvironmentNotSupportedError` | GPU/CUDA 格不在 manifest；执行 `flashcli models envs pi05_libero` 并 sync 新版 bundle |
| `no kernel image...` | GPU/CUDA 格不匹配；在本机执行 `flashcli models envs pi05_libero` |
| `'GemmRunner'... fp8_nt_dev` | 更新 FlashRT 并重编，或 bundle 内 `_pi05_compat.py` shim |
| `FvkContext is already registered` | 升级 flashcli |
