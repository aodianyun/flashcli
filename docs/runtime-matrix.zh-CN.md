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

## 矩阵构建（通用脚本）

配置在 `bundles/<name>/release-matrix.env`；bundle 实现标准 hook（见 `scripts/lib/bundle_hooks.sh`）。

| 能力 | `release_bundle.sh` / `build_release_matrix.sh` |
|------|--------------------------------------------------|
| 双重循环 cu124/130 × py310/311/312 | ✅ |
| 自动 clone FlashRT | ✅（`release_bundle.sh` 默认） |
| Docker 双镜像（cu124/cu130） | ✅（`release_bundle.sh` 默认） |
| 安装 Python 3.10/3.11/3.12 | `--install-python` |
| `--cuda-tag` | 只编一条 CUDA 线 |

每一格：**换 Python + 独立 build 目录 + cmake**；`matrix_cell.sh` 只写本格 `lib/*.so`，不改 manifest。

## 构建

**推荐：一键发布**

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --git-ref main --clean
# 等价：bash scripts/release_bundle.sh --bundle pi05_libero --clean
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

产物：`bundles/pi05_libero/dist/*.zip` → 上传 CDN → 更新 `models.yaml`。

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

## qwen_nvfp4（SM120 × cu124/cu130）

| 维度 | 取值 |
|------|------|
| SM | **120**（Blackwell NVFP4） |
| CUDA 用户态 | **cu124**、**cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12** |
| Native 模块 | `flash_rt_kernels`（含 NVFP4）、`flash_rt_fa2` |

一个 zip 服务两个 catalog preset（`qwen3-8b-nvfp4`、`qwen36-27b-nvfp4`），权重由 HF 拉取，**不在 zip 内**。

### 发布构建

```bash
cd flashcli/bundles/qwen_nvfp4
bash release.sh --git-ref main --clean
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
