# pi05_libero

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

Pi0.5 LIBERO VLA，权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)。

**对外 preset**：`pi05_libero`（[`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)）。用户端按 GPU 环境从 **`bundle.variants`** 拉取对应 CDN zip（当前已发布：`sm89-cu124-linux-x86_64`）。可用 `flashcli models envs pi05_libero` 查看本机是否匹配。

## 运行所需文件（zip 根目录）

与实测一致，推理只需：

```text
flashcli-bundle.json
run.py
_pi05_compat.py
flash_rt_kernels.so
flash_rt_fa2.so
flash_rt/                 # 裁剪后的 Python（无 .so）
```

权重由 flashcli 下载到 `~/.flashcli/models/pi05_libero/checkpoint/`，**不**打进 bundle。

## 用户

```bash
pip install flashcli
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## 维护者：组装 bundle

**Linux + NVIDIA GPU**（SM89 或 SM120）：

```bash
cd flashcli/bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
bash pack.sh --sm 89                    # 仅打开发布 zip（cuda 标签由 nvcc 自动检测，通常为 cu124）
```

发布后在 `src/flashcli/catalog/models.yaml` 中为对应环境键登记 zip URL，例如：

```yaml
bundle:
  variants:
    sm89-cu124-linux-x86_64:
      zip: https://cdn.../flashcli-bundle-pi05-main-sm89-cu124-linux-x86_64.zip
```

`build.sh` 仅打入 Pi0.5 RTX 路径需要的 `flash_rt/` 子树，并只复制 `flash_rt_kernels.so`、`flash_rt_fa2.so`。

**不需要** `requirements-runtime.txt`：pip 依赖已在 `flashcli-bundle.json` 的 `python_dependencies` 中，该 txt 仅为旧版冗余副本，发布 zip 请勿包含。

```bash
flashcli bundle validate "$(pwd)/bundles/pi05_libero"
flashcli run pi05_libero --bundle "$(pwd)/bundles/pi05_libero" --image /path/to/base.jpg
```

## 排错

### HuggingFace 权重下载失败（`LocalEntryNotFoundError`）

bundle zip 只含 runtime；约 7.5GB 权重需从 Hub 拉取。K8s/内网若无法访问 `huggingface.co` 与 `hf-mirror.com`，会报此错误（多为网络/DNS/代理，而非仓库不存在）。

flashcli 下载权重与官方 CLI 相同：设置 `HF_ENDPOINT` 后调用 `hf download`（或 `huggingface-cli download`）。**请先** `export HF_ENDPOINT=https://hf-mirror.com`，再执行 `flashcli pull/run`。

```bash
# 诊断：用 GET（不要用 curl -I / HEAD，镜像可能对 HEAD 返回 308）
curl -fsSL 'https://hf-mirror.com/api/models/lerobot/pi05_libero_finetuned_v044/revision/main' | head -c 80

# 1) 清理不完整缓存后重试
rm -rf ~/.flashcli/models/pi05_libero/checkpoint

# 2) 与 hf download 相同：在启动 flashcli 之前 export
export HF_ENDPOINT=https://hf-mirror.com
# 未设置 HF_ENDPOINT 时默认先试官方 Hub，失败再试镜像；仅镜像优先：export FLASHCLI_PREFER_HF_MIRROR=1

flashcli pull pi05_libero
# 或带本地 bundle：
flashcli run pi05_libero --bundle "$(pwd)/bundles/pi05_libero" --image /path/to.jpg
```

有代理时设置 `HTTPS_PROXY` / `HTTP_PROXY`。也可在能联网的机器预下载后拷贝：

```bash
huggingface-cli download lerobot/pi05_libero_finetuned_v044 \
  --local-dir ./checkpoint

flashcli run pi05_libero --bundle bundles/pi05_libero \
  --checkpoint ./checkpoint --image /path/to.jpg
```

`--bundle` 应指向含 `flashcli-bundle.json` 的目录（如 `bundles/pi05_libero` 或解压后的 `dist/flashcli-bundle-pi05-*`），不是 zip 文件本身。

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

SM89：`_pi05_compat.py` 提供 shim，或重新 build 含 `fp8_nt_dev` 的 FlashRT。

### `FvkContext is already registered`

使用最新 flashcli；内核在 `run.py` 加载流程中只注册一次。
