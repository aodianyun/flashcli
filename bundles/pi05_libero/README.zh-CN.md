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

### FA2 与 SM120

发布矩阵标签为 **sm89**，但 `requires.sm` 含 **120**（Blackwell 可选用同一份制品）。**发布构建默认关闭 `FA2_ARCH_NATIVE_ONLY`**，FA2 含 `sm_80 + sm_120 + PTX`，否则 SM120 会报：

```text
no kernel image is available for execution on the device
```

本地单卡快速迭代可加 `--fa2-native-only`（仅当前 GPU 架构，**不可用于发布**）。

### 一键发布（推荐）

宿主机需 **Linux + Docker + NVIDIA GPU**（矩阵在容器内编译）。自动 clone/update FlashRT、双 CUDA 线（cu124/cu130）× Python 3.10/3.11/3.12、写 manifest、打 zip：

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --git-ref main --clean
```

等价：

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --git-ref main --clean
```

`--clean` 会删除 `lib/`、`dist/`、`.build-matrix/`、`.native-cache/`（避免复用旧 FA2 单架构缓存）。

产物：

```text
bundles/pi05_libero/dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64-YYYYMMDD-HHMMSS.zip
```

### 分步发布（宿主机已有 cu124 + cu130）

```bash
cd flashcli

# 0) 可选：检查 Python / nvcc 布局
bash scripts/build_release_matrix.sh --bundle pi05_libero --check-only

# 1) 编矩阵（每条 CUDA 线 3 个 Python ABI，FA2 多架构，耗时较长）
bash scripts/release_bundle.sh --bundle pi05_libero --clean --cuda-tag 124
bash scripts/release_bundle.sh --bundle pi05_libero --cuda-tag 130

# 2) 第二条 CUDA 线跑完会自动 finalize + pack；若只编了一条，补跑：
bash scripts/build_release_matrix.sh --bundle pi05_libero --pack-only

# 3) 校验
flashcli bundle validate bundles/pi05_libero
```

无 Docker、双 CUDA 已在宿主机时可用 `--native`：

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --native --clean
```

指定本地 FlashRT：

```bash
export FLASHRT_REPO=/path/to/FlashRT
bash release.sh --clean --repo-root "$FLASHRT_REPO"
```

### 发布后

1. **本机抽测**（有对应 GPU 时）：

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --benchmark 5
```

2. **上传** `dist/*.zip` 到 CDN。

3. **更新** [`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml) 中 `pi05_libero.bundle.zip` URL。

4. **SM120 验收**（如 RTX PRO 5000）：

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

### `no kernel image is available for execution on the device`（FA2 / SM120）

多出现在 **SM120**（Blackwell）上跑**旧版** bundle：`flash_rt_fa2` 仅含 sm_89 SASS。请用**新脚本重打 bundle**（默认 FA2 多架构），或本地开发时不要对发布产物使用 `--fa2-native-only`。

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

SM89：`_pi05_compat.py` 提供 shim，或重新 build 含 `fp8_nt_dev` 的 FlashRT。

### `FvkContext is already registered`

使用最新 flashcli；内核在 `run.py` 加载流程中只注册一次。
