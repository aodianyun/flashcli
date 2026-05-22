# Runtime 发布矩阵（pi05_libero）

<p align="right"><a href="runtime-matrix.md">English</a> · <strong>简体中文</strong></p>

## 当前紧急维护范围

| 维度 | 取值 |
|------|------|
| SM | **89**（SM120 通过 catalog 别名共用 SM89 包） |
| CUDA 用户态 | **cu124**、**cu130** |
| OS / arch | **linux-x86_64** |
| Python ABI | **3.10 / 3.11 / 3.12**（catalog 后缀 `-py310` / `-py311` / `-py312`） |

## 推荐：单 zip 多环境（`native_layout: matrix`）

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

`models.yaml` **不再使用** `bundle.variants`；每个 preset 仅一个 `bundle.zip`。

`models.yaml` 只需一个 `bundle.zip`（见 `schema_version: 6`），不再按环境拆 6 个 CDN 包。

构建 cu124 三档 Python（单 zip）：

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
```

---

## 旧方案：每环境单独 zip（仍兼容）

共 **6 个独立 CDN zip**（每个格子单独编译 `flash_rt_*.so`，不能混用 Python 版本）。

### Native `.so` 命名（便于复用）

构建后 `lib/` 下的扩展名格式：

```text
{模块}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

示例：

```text
flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-abc1234-sm89-cu124-linux-x86_64-py312.so
```

- **FlashRT_ABI**：`git describe` 消毒后的标签，过长时用 `git commit` 前 12 位  
- 同 tag 的 `.so` 会缓存到 `flashcli/.native-cache/<tag>/`，换 zip 名 / 只改 manifest 时可 `--pack-only` 复用  
- `flashcli run` 按 `modules[].file` 加载，import 名仍为 `flash_rt_kernels` / `flash_rt_fa2`

| catalog 键 | zip 文件名（示例） |
|------------|-------------------|
| `sm89-cu124-linux-x86_64-py310` | `flashcli-bundle-pi05-main-sm89-cu124-linux-x86_64-py310.zip` |
| `sm89-cu124-linux-x86_64-py311` | `...-py311.zip` |
| `sm89-cu124-linux-x86_64-py312` | `...-py312.zip` |
| `sm89-cu130-linux-x86_64-py310` | `...-cu130-...-py310.zip` |
| … | cu130 × py311/py312 同理 |

登记位置：[`src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)。

## 与 install.sh / run 的分工

| 阶段 | 安装内容 |
|------|----------|
| `install.sh` | 仅 flashcli CLI（`pyproject.toml` [project]） |
| `flashcli run` | 按本机 GPU + **当前 Python** 选 zip → pip 装 torch（`cu124`/`cu130` 索引）→ 加载 `.so` |

本机环境键示例（RTX 4060 Ti + Python 3.12）：

```text
sm89-cu124-linux-x86_64-py312
```

查看匹配：`flashcli models envs pi05_libero`

## 如何生成 6 个 zip

### 脚本实际做了什么 / 没做什么

| 能力 | `build_pi05_release_matrix.sh` |
|------|--------------------------------|
| 双重循环 cu124/130 × py310/311/312 | ✅ 有 |
| 安装 Python 3.10/3.11/3.12 | ❌ 默认没有；可加 `--install-python`（apt） |
| 切换 CUDA 工具链 | ✅ 通过 **`CUDA_HOME_CU124` / `CUDA_HOME_CU130`** 在每一格编译前设置 `PATH`；**不会**自动装 CUDA |
| `--cuda-tag` | 校验本格 `nvcc` 版本与标签一致，并写入 manifest / zip 名；**不是**只改文件名 |

每一格都会：**换 Python 解释器 + 换独立 `build-matrix-cu*-py*` 目录 + 全量 cmake 编译**（6 格 = 6 次 native 编译）。

### 最快上手（推荐顺序）

**1）先检查环境（不编译）**

```bash
cd flashcli
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4   # 按你机器路径改
export CUDA_HOME_CU130=/usr/local/cuda-13.0   # 若没有 13，先只编 124

bash scripts/build_pi05_release_matrix.sh --check-only
```

**2）缺 Python 时（Debian/Ubuntu）**

```bash
sudo bash scripts/build_pi05_release_matrix.sh --install-python --check-only
```

`--install-python` 会**按版本逐个 apt 安装**；Debian 默认源常**没有** `python3.12`，脚本会跳过并提示，不会整批失败。

**K8s / Debian 没有 python3.12 apt 包时（推荐）** — 用独立 Python 构建包装 3.11+3.12，再一次打出 cu124 三个 zip：

```bash
cd /app/flashcli
sudo bash scripts/install_python_for_matrix.sh --minors 310,311,312
# 或已有 3.12 只补 3.10/3.11：
# sudo bash scripts/install_python_for_matrix.sh --minors 310,311 --method auto

source /root/.flashcli/python-matrix.env
export CUDA_HOME_CU124=/usr/local/cuda-12.4   # 按机器改
export FLASHRT_REPO=/path/to/FlashRT

bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → dist 下 3 个 zip：py310 / py311 / py312
```

若机器上已有 `/usr/local/bin/python3.12`：

```bash
export FLASHCLI_PY312_BIN=/usr/local/bin/python3.12
bash scripts/build_pi05_release_matrix.sh --check-only
```

只维护已有 Python 时，可只编对应格：

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124 --python-minor 312
```

**3）只有 CUDA 12.4 时 — 先出 3 个 zip（最常见）**

```bash
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → py310 / py311 / py312 各一个 cu124 zip
```

**4）再上 CUDA 13 的 3 个 zip**

```bash
export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_pi05_release_matrix.sh --cuda-tag 130
```

**5）完整 6 格（机器上同时有两套 toolkit）**

```bash
export CUDA_HOME_CU124=/usr/local/cuda-12.4
export CUDA_HOME_CU130=/usr/local/cuda-13.0
bash scripts/build_pi05_release_matrix.sh
```

产物：`bundles/pi05_libero/dist/*.zip` → 上传 CDN → 核对 `models.yaml` URL。

### 单格手动流程

```bash
PY=python3.10   # 或 python3.11 / python3.12
CUDA=124        # 或 130（构建机 nvcc / CMake 需对应该 CUDA 线）

# 1) 用指定 Python 编译 FlashRT .so（见 build_pi05_bundle.sh 内 CMake）
bash scripts/build_pi05_bundle.sh \
  --bundle-dir bundles/pi05_libero \
  --repo-root "$FLASHRT_REPO" \
  --python-bin "$PY" \
  --sm 89 \
  --cuda-tag "$CUDA"

# 2) 打 zip
bash bundles/pi05_libero/pack.sh --sm 89 --cuda-tag "$CUDA" --python-minor 310
```

**cu130 格子**：构建机安装 CUDA 13 工具链，`--cuda-tag 130`，`recommended_torch_index` 会为 `cu128`/`cu130`（见 `build_pi05_bundle.sh`）。

**不要** 用 Python 3.12 解释器加载 `-py310` zip（会在 `activate_bundle` 阶段报错）。

## SM120 别名

SM120 机器 catalog 键为 `sm120-cu128-...-pyNNN` 或 `sm120-cu130-...-pyNNN`，指向对应 `sm89-cu124/cu130-...-pyNNN` zip（`requires.sm` 含 120）。

## 本地调试（不经过 CDN）

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

本地 bundle 须用**同一 Python** 构建 `.so`。
