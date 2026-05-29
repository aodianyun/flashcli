# pi05_libero

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

Pi0.5 LIBERO VLA，权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)。

**对外 preset**：`pi05_libero`（[`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)）。用户端拉取**单个** CDN zip；flashcli 按本机 GPU + Python 在 `lib/` 中选匹配 `.so`。可用 `flashcli models envs pi05_libero` 查看本机环境键是否匹配。

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

## 维护者：发布 bundle

**推荐（一键，自动拉 FlashRT + 双 Docker 编矩阵 + 打包）：**

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --git-ref main --clean
```

产物：`dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip`

**本地单环境开发**（不跑完整矩阵）：

```bash
bash build.sh --repo-root /path/to/FlashRT
flashcli bundle validate .
```

矩阵维度见 `release-matrix.env`（sm89 × cu124/cu130 × py310/311/312）。细节：[docs/runtime-matrix.zh-CN.md](../../docs/runtime-matrix.zh-CN.md)、[scripts/lib/bundle_hooks.sh](../../scripts/lib/bundle_hooks.sh)。

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
