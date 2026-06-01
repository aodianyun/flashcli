# Runtime 发布矩阵

<p align="right"><a href="runtime-matrix.md">English</a> · <strong>简体中文</strong></p>

维护者如何构建 **多环境原生矩阵**（`lib/*.so`）并发布 **每个模型一个 zip**。终端用户只安装单个 `bundle.zip`；运行时由 flashcli 自动选型。

## 矩阵概览

| Bundle | SM 标签 | CUDA 线 | Python ABI | Native 模块 |
|--------|---------|---------|------------|---------------|
| `pi05_libero` | **89** | **cu124**、**cu130** | 3.10 / 3.11 / 3.12 | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen_nvfp4` | **120** | **仅 cu130** | 3.10 / 3.11 / 3.12 | `flash_rt_kernels`（含 NVFP4）, `flash_rt_fa2` |

OS / arch：均为 **linux-x86_64**。配置见 `bundles/<name>/release-matrix.env`。

## 单 zip 多环境（`native_layout: matrix`）

一个模型 **一个 runtime zip**，所有环境的 `.so` 放在 **`lib/`**（扁平，无 `lib/native` 子目录）：

```text
pi05_libero/
  flashcli-bundle.json    # native_layout: matrix, native_matrix: [...]
  lib/
    flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py310.so
    flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py310.so
    ... py311, py312, cu130 等同名规则 ...
  flash_rt/
  run.py
```

**`flashcli run`** 时根据本机 `sm + cuda + os + arch + Python` 在 `lib/` 里选匹配的一份；**没有匹配则明确报错**（`NativeEnvironmentNotSupportedError`）。

每个 preset 在 `models.yaml` 中仅一个 `bundle.zip`（`schema_version: 6`）。

### Native `.so` 命名

```text
{模块}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

示例：

```text
flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-abc1234-sm89-cu124-linux-x86_64-py312.so
```

- **FlashRT_ABI**：`git describe` 消毒后的标签，过长时用 `git commit` 前 12 位
- 同 tag 的 `.so` 会缓存到 `flashcli/.native-cache/<tag>/`，可 `--pack-only` 复用
- import 名仍为 `flash_rt_kernels` / `flash_rt_fa2`

### Release zip 命名

```text
{ZIP_PREFIX}-{FlashRT_ABI}-sm{SM}-multi-linux-x86_64-{YYYYMMDD-HHMMSS}.zip
```

示例：`flashcli-bundle-pi05-7cf622f-sm89-multi-linux-x86_64-20260529-193354.zip`（见 `scripts/pack_bundle.sh`）。

### FA2 与 SM120（pi05_libero）

矩阵在 **SM89** 标签（`GPU_ARCH=89`）上编译，但 `flashcli-bundle.json` 的 `requires.sm` 含 `120`。

| CUDA 线 | FA2 策略 | 原因 |
|---------|----------|------|
| **cu124**（nvcc 12.4） | `FA2_ARCH_NATIVE_ONLY` → sm_89 AOT | nvcc 12.4 **不能**编 `compute_120` |
| **cu130**（nvcc 13.x） | 默认 sm_80 + sm_120 + PTX | Blackwell 用户选 cu130 格 |

因此：**SM120 用户应匹配 `*-cu130-*` 的 `.so`**；cu124 格只服务 CUDA 12.4 + SM89（及兼容路径）。本地单卡加速可加 `build.sh --fa2-native-only`（仅开发，勿发布）。

登记位置：[`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)。包格式：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 矩阵构建（通用脚本）

配置在 `bundles/<name>/release-matrix.env`；cmake/staging 在 `bundles/<name>/_bundle_build.sh`；共享 orchestration 见 `scripts/lib/bundle_hooks.sh`。

| 脚本 | 作用 |
|------|------|
| `scripts/release_bundle.sh` | **推荐**：FlashRT → Docker/`--native` 矩阵 → finalize → pack |
| `scripts/build_release_matrix.sh` | 宿主机矩阵循环 |
| `scripts/pack_bundle.sh` | 矩阵/ABI 校验 + 打 zip |
| `scripts/run_bg.sh` | 可选：后台运行 + 本地日志 |
| `scripts/lib/bundle_hook_runner.sh` | 调用 `_bundle_build.sh` 编单格 / finalize |

| 能力 | 支持 |
|------|------|
| cu124/130（或 bundle 声明的 CUDA 线）× py310/311/312 | ✅ |
| 自动 clone/update FlashRT | ✅（`release_bundle.sh` 默认） |
| Docker 双镜像 | ✅（pi05；qwen 仅 cu130） |
| `--cuda-tag` | 只编一条 CUDA 线 |

每一格：**换 Python + 独立 build 目录 + cmake**；通过 `--merge-native` 只写本格 `lib/*.so`，finalize 阶段再更新 `flashcli-bundle.json`。

### Python ABI 校验（编译后立即执行）

矩阵编完后，[`build_release_matrix.sh`](../scripts/build_release_matrix.sh) 会用**编译同一套**的 Python（`install_python_for_matrix.sh` 写入的 `FLASHCLI_PY310_BIN` 等）立刻探测 `lib/*.so`：

1. **单格** — `_bundle_build.sh` 在 staging 后探测；**ABI 不匹配（`rc=2`）直接失败**。
2. **矩阵结束** — `verify_native_lib_python_abi`（[`scripts/lib/verify_native_abi.sh`](../scripts/lib/verify_native_abi.sh)）对合并后的 `lib/` 再验一遍，然后才 pack。

Docker 会把解释器持久化到挂载的 workspace（`/workspace/.flashcli-python`、`/workspace/.flashcli/python-matrix.env`），宿主机 pack 时可复用：

```bash
source ../.flashcli/python-matrix.env
bash scripts/pack_bundle.sh --bundle-dir bundles/qwen_nvfp4 --repo-root ../FlashRT
```

宿主机若没有三个 Python，pack 仍会打 zip（矩阵文件校验通过即可），ABI 探测会 WARN 跳过；**以编译机上的校验为准**。`flashcli bundle validate` 仍为可选。

## 构建

**推荐：一键发布**

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --clean
# 等价：bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

后台 + 日志：

```bash
bash scripts/run_bg.sh --name release-pi05 -- \
  bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

**分步（宿主机 Linux，已有两套 CUDA）**

```bash
cd flashcli
bash scripts/build_release_matrix.sh --bundle pi05_libero --check-only
bash scripts/build_release_matrix.sh --bundle pi05_libero --cuda-tag 124 --skip-pack
bash scripts/build_release_matrix.sh --bundle pi05_libero --cuda-tag 130 --skip-pack
bash scripts/build_release_matrix.sh --bundle pi05_libero --pack-only
```

只编某一格：

```bash
bash scripts/build_release_matrix.sh --bundle pi05_libero --cuda-tag 124 --python-minor 312
```

产物示例：`bundles/pi05_libero/dist/flashcli-bundle-pi05-{abi}-sm89-multi-linux-x86_64-{时间戳}.zip` → 上传 CDN → 更新 `models.yaml`。

### 本地单环境开发

```bash
cd bundles/pi05_libero
bash build.sh --repo-root "$FLASHRT_REPO"
```

## 运行时选择

| 阶段 | 安装内容 |
|------|----------|
| `install.sh` | 仅 flashcli CLI |
| `flashcli run` | 按 bundle `python_dependencies` 装 torch → 从 `lib/` 选匹配 `.so` |

本机环境键示例（RTX 4060 Ti + Python 3.12）：

```text
sm89-cu124-linux-x86_64-py312
```

查看匹配：`flashcli models envs pi05_libero`

**不要** 用 Python 3.12 加载仅含 `-py310` 制品的 bundle（会在 `activate_bundle` 阶段报错）。

## 本地调试（不经过 CDN）

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

---

## qwen_nvfp4（SM120 × cu130）

| 维度 | 取值 |
|------|------|
| SM | **120**（Blackwell NVFP4） |
| CUDA 用户态 | **cu130**（需 nvcc ≥ 12.8 编 sm_120/sm_120a；**无 cu124 线**） |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12** |
| Native 模块 | `flash_rt_kernels`（含 NVFP4）、`flash_rt_fa2` |

一个 zip 服务两个 catalog preset（`qwen3-8b-nvfp4`、`qwen36-27b-nvfp4`），权重由 HF 拉取，**不在 zip 内**。

### 发布构建

```bash
cd flashcli/bundles/qwen_nvfp4
bash release.sh --clean
# 等价：bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

需 **Linux + Docker + GPU**（或宿主机 `--native` + CUDA 13）。**无 cu124 线**（nvcc 12.4 无法编 sm_120/sm_120a）。

产物示例：

```text
bundles/qwen_nvfp4/dist/flashcli-bundle-qwen_nvfp4-{abi}-sm120-multi-linux-x86_64-{时间戳}.zip
```

上传 CDN 后更新 `models.yaml` 中两个 preset 的 `bundle.zip`（URL 相同）。

单档开发：

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

环境键示例：`sm120-cu130-linux-x86_64-py312`。查看匹配：

```bash
flashcli models envs qwen3-8b-nvfp4
```
