# Runtime 发布矩阵（pi05_libero）

<p align="right"><a href="runtime-matrix.md">English</a> · <strong>简体中文</strong></p>

## 当前维护范围

| 维度 | 取值 |
|------|------|
| SM | **89**（SM120 在 `requires.sm` 允许时使用 SM89 制品） |
| CUDA 用户态 | **cu124**、**cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12**（`-py310` / `-py311` / `-py312`） |

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

登记位置：[`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)。包格式：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

## 矩阵脚本行为

| 能力 | `build_pi05_release_matrix.sh` |
|------|--------------------------------|
| 双重循环 cu124/130 × py310/311/312 | ✅ |
| 安装 Python 3.10/3.11/3.12 | ❌ 默认没有；可加 `--install-python`（apt） |
| 切换 CUDA 工具链 | ✅ 通过 `CUDA_HOME_CU124` / `CUDA_HOME_CU130` |
| `--cuda-tag` | 校验 `nvcc` 与标签一致，写入 manifest / zip 名 |

每一格：**换 Python 解释器 + 独立 build 目录 + 全量 cmake**（每个 Python/CUDA 组合各编译一次 native）。

## 构建

**1）先检查环境（不编译）**

```bash
cd flashcli
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4
export CUDA_HOME_CU130=/usr/local/cuda-13.0   # 若没有 13，先只编 124

bash scripts/build_pi05_release_matrix.sh --check-only
```

**2）缺 Python 时（Debian/Ubuntu）**

```bash
sudo bash scripts/build_pi05_release_matrix.sh --install-python --check-only
```

**3）cu124 × 三档 Python → 一个多环境 zip**

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
```

**4）再上 cu130**

```bash
export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_pi05_release_matrix.sh --cuda-tag 130
```

只编某一格时：

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124 --python-minor 312
```

产物：`bundles/pi05_libero/dist/*.zip` → 上传 CDN → 核对 `models.yaml` URL。

### 单格手动流程（维护者本地）

```bash
bash scripts/build_pi05_bundle.sh \
  --bundle-dir bundles/pi05_libero \
  --repo-root "$FLASHRT_REPO" \
  --python-bin python3.12 \
  --sm 89 \
  --cuda-tag 124
```

须用**与运行 flashcli 相同的 Python** 构建 `.so`。

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
| CUDA 用户态 | **cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12** |
| Native 模块 | `flash_rt_kernels`、`flash_rt_fa2`、`flash_rt_fp4` |

一个 zip 服务两个 catalog preset（`qwen3-8b-nvfp4`、`qwen36-27b-nvfp4`），权重由 HF 拉取，**不在 zip 内**。

### 发布构建

```bash
cd flashcli
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU130=/usr/local/cuda-13.0

bash scripts/build_qwen_release_matrix.sh --check-only
bash scripts/build_qwen_release_matrix.sh
```

产物：

```text
bundles/qwen_nvfp4/dist/flashcli-bundle-qwen_nvfp4-main-sm120-multi-linux-x86_64.zip
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
