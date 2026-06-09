# pi05_libero

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

Pi0.5 LIBERO VLA，权重 [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044)。

**对外 preset**：`pi05_libero`（[`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)）。用户通过 FlashHub `bundle.repo` sync runtime；flashcli 按本机 GPU + CUDA 匹配 manifest 中的 `runtime` env key，并将 `.so` 装入 `lib/`。可用 `flashcli models envs pi05_libero` 查看本机环境键是否匹配。

## 运行所需文件（sync 后 bundle 根）

```text
flashcli-bundle.json
run.py
_pi05_compat.py
lib/                       # 本机 env 的 *.so（来自 runtime/<env-key>/）
flash_rt/
```

权重由 flashcli 下载到 `~/.flashcli/models/pi05_libero/checkpoint/`，**不**打进 bundle。

## 用户

命令速查见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**。

```bash
pip install flashcli
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## 维护者：发布 bundle

**支持 GPU**：**仅 SM89**（Ada，如 RTX 4090）。SM120 / Blackwell 暂不在此 release 线支持范围内。

### FA2 编译（矩阵）

| CUDA 线 | FA2 |
|---------|-----|
| **cu124**（nvcc 12.4） | 仅 sm_89 AOT（`FA2_ARCH_NATIVE_ONLY`） |
| **cu130**（nvcc 13.x） | sm_80 + sm_120 + PTX（cu130 格内 FA2 多架构；**kernels 仍为 sm_89**） |

本地单卡 SM89 加速：`build.sh --fa2-native-only`（**不可用于发布**）。

### 一键发布（推荐）

宿主机需 **Linux + Docker + NVIDIA GPU**（矩阵在容器内编译）。自动 clone/update FlashRT、双 CUDA 线（cu124/cu130）× Python 3.10/3.11/3.12、写 manifest、打 zip：

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --clean
```

等价：`bash scripts/release_bundle.sh --bundle pi05_libero --clean`

`--clean` 会删除 `lib/`、`dist/`、`.build-matrix/`、`.native-cache/`。

产物在 `dist/`（源码树 + `runtime/<env-key>/`）。

### 发布后

1. **本机抽测**（有对应 GPU 时）：

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --benchmark 5
```

2. **上传** `dist/` 到 FlashHub。

3. **更新** [`models.yaml`](../../src/flashcli/catalog/models.yaml) 中 `pi05_libero.bundle.repo` 版本 URL。

4. **SM89 验收**（如 RTX 4090）：

```bash
flashcli models envs pi05_libero
flashcli run pi05_libero --benchmark 5
```

### 本地单环境开发

不跑完整矩阵，只编当前机子的一个 cu×py 档：

```bash
cd flashcli/bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
flashcli bundle validate .
```

仅本机 SM89、加快 FA2 编译：

```bash
bash build.sh --repo-root /path/to/FlashRT --fa2-native-only
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

### `no kernel image is available for execution on the device`

多为 **GPU 不符**（SM120 暂不支持）或 SM89 上 **CUDA 格不匹配**。执行 `flashcli models envs pi05_libero`，应匹配 `sm89-cu124-*` 或 `sm89-cu130-*`。

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

SM89：`_pi05_compat.py` 提供 shim，或重新 build 含 `fp8_nt_dev` 的 FlashRT。

### `FvkContext is already registered`

使用最新 flashcli；内核在 `run.py` 加载流程中只注册一次。
