# Bundle 构建与发布指南

<p align="right"><a href="bundle_builder_guide.md">English</a> · <strong>简体中文</strong></p>

面向 **Model Bundle 构建方**：从环境安装、本地开发、矩阵编译、打包校验，到上传 FlashHub 与更新 catalog。  
格式规范见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)；终端用户命令见各 bundle 的 `QUICKSTART.zh-CN.md`。

---

## 1. 你要做什么

| 角色 | 目标 | 需要装什么 |
|------|------|------------|
| **Bundle 构建者** | 改 `run.py` / `flashcli-bundle.json`，编译 FlashRT，发布 zip | flashcli + flashcli-bundle（editable）+ FlashRT + Docker/GPU |
| **终端用户** | `flashcli run <preset>` | 仅 `install.sh` / `pip install flashcli` |

Bundle **entry 代码只 import `flashcli_bundle`**，不要 import `flashcli` CLI 包：

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.protocol import ChatRequest, RunEngine
from flashcli_bundle.preset import Preset
```

---

## 2. 推荐环境（含镜像）

### 硬件

| Bundle | GPU | CUDA 用户态 | 说明 |
|--------|-----|-------------|------|
| `pi05_libero` | **SM89**（Ada，如 4090 / 4060 Ti） | cu124 或 cu130 | 不支持 SM120 |
| `qwen_nvfp4` | **SM120**（Blackwell） | **仅 cu130** | NVFP4 需 nvcc ≥ 12.8 |

### 软件

- **OS**：Linux x86_64
- **Docker + NVIDIA Container Toolkit**（矩阵发布默认走容器）
- **Python 3.10+**（主机 CLI）；bundle venv 固定 **3.12**（`python_abi: "312"`）

### 国内 / 受限网络（推荐）

```bash
# 1) 安装 flashcli（Gitee + pip/HF 镜像）
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror

# 2) 或指定分支
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror --ref main

# 3) Hugging Face 权重镜像（pull/run 前）
export HF_ENDPOINT=https://hf-mirror.com

# 4) pip 镜像（install.sh --mirror 已设；手动 pip 时）
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
export PIP_TRUSTED_HOST=mirrors.aliyun.com
```

Qwen 矩阵容器镜像：`nvcr.io/nvidia/pytorch:25.10-py3`（见各 bundle 的 `release-matrix.env`）。

---

## 3. 工作区布局

```text
workspace/
├── flashcli/                 # git clone 本仓库
│   ├── flashcli-bundle/      # 协议包（与 flashcli 同 repo）
│   ├── bundles/
│   │   ├── pi05_libero/
│   │   └── qwen_nvfp4/
│   ├── scripts/
│   │   └── release_bundle.sh
│   └── src/flashcli/
└── FlashRT/                  # 推理内核（release 脚本可自动 clone）
```

```bash
git clone https://gitee.com/aodiansoft/flashcli.git   # 或 GitHub
cd flashcli

# 开发安装（构建者必做）
pip install -e ./flashcli-bundle
pip install -e .

flashcli doctor
flashcli models list
```

---

## 4. Bundle 目录结构

以 `bundles/pi05_libero/` 为例：

```text
pi05_libero/
├── flashcli-bundle.json      # manifest（必填字段见下）
├── run.py                    # entry.run → RunEngine
├── _pi05_compat.py           # bundle 私有 helper
├── flash_rt/                 # FlashRT Python 树（staging）
├── lib/                      # 本地 build：本机 *.so
├── runtime/                  # pack 后：runtime/<env-key>/*.so
├── release-matrix.env        # 发布矩阵（SM、CUDA、py ABI）
├── _bundle_build.sh          # cmake + 编译逻辑
├── build.sh                  # 本地单环境 build
├── release.sh                # → scripts/release_bundle.sh
└── dist/                     # 发布产物（上传 FlashHub）
```

### manifest 必填要点（format_version 3）

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "pi05_libero",
  "python_abi": "312",
  "entry": { "run": { "module": "run", "attr": "RunEngine" } },
  "run_options": [ ... ],
  "python_dependencies": {
    "torch": { "package": "torch", "index": "auto" }
  },
  "runtime": {
    "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312"
  }
}
```

- **`protocol_version`**：必须与已安装 `flashcli-bundle` 的 `PROTOCOL_VERSION` 一致（当前为 **1**）。
- **`run_options` / `serve_options`**：CLI 参数与默认值唯一来源；`run.py` 用 `run_option_defaults()`，勿写死字面量。
- **有 `variants` 时**：每个 variant 各自完整的 `run_options` / `serve_options`，禁止顶层重复。

---

## 5. 本地开发循环（不跑完整矩阵）

**目的**：在本机 GPU 上编一个 env 的 `.so`，快速改 entry / 测 `run`。

### 步骤 A — 编译 native

```bash
cd flashcli
export FLASHRT_REPO=/path/to/FlashRT   # 或省略，由脚本 clone

bash bundles/pi05_libero/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
```

**做什么**：`_bundle_build.sh` 调 FlashRT cmake，产出 `lib/flash_rt_*.so`，并 staging `flash_rt/`。

### 步骤 B — 校验 manifest 与 layout

```bash
export BUNDLE="$(pwd)/bundles/pi05_libero"
flashcli bundle validate "$BUNDLE"
```

**做什么**：检查 `flashcli-bundle.json`、entry 文件、`run_options` 布局、`protocol_version`、本机 env 的 native ABI（若 `--probe-abi`）。

### 步骤 C — 拉权重 + smoke run

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 内网推荐

flashcli pull pi05_libero --bundle "$BUNDLE"

flashcli run pi05_libero --bundle "$BUNDLE" \
  --prompt "pick up the red block" \
  --image /path/to/base.jpg

flashcli run pi05_libero --help    # 查看 manifest run_options
```

**做什么**：主机 CLI sync → 建 bundle venv（3.12）→ 装 torch + **flashcli-bundle** → re-exec → 执行你的 `run.py`。

Qwen serve 本地测：

```bash
flashcli serve qwen3-8b-nvfp4 --bundle "$BUNDLE" --host 127.0.0.1 --port 8000
flashcli serve qwen3-8b-nvfp4 --help
```

---

## 6. 正式发布流水线（逐步说明）

**一条命令**（在 `flashcli` 仓库根目录）：

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --clean
# 或
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

等价于进入 `bundles/<name>/` 执行 `bash release.sh --clean`。

### 脚本内部阶段

| 阶段 | 做什么 | 产出 |
|------|--------|------|
| **1. 读 `release-matrix.env`** | 确定 SM、CUDA tags、Python ABI、Docker 镜像、打包文件列表 | 矩阵维度 |
| **2. 确保 FlashRT** | clone/update `../FlashRT`（可 `export FLASHRT_REPO=` 覆盖） | 源码 |
| **3. Docker 矩阵 build** | 每个 CUDA 线在对应 nvcr 容器内跑 `_bundle_build.sh` | 各 env 的 `.so` |
| **4. 写入 `runtime/`** | 按 env key 分目录：`runtime/sm89-cu124-linux-x86_64-py312/` 等 | native 制品 |
| **5. `pack_bundle.sh`** | 复制 entry、`flash_rt/`、刷新 manifest `runtime` map | `dist/` 源码树 |
| **6. 校验** | ABI / layout / manifest options / protocol | 失败则 exit |
| **7. 打 zip** | `dist/flashcli-bundle-<name>-*.zip` | 上传 FlashHub 用 |

`--clean`：删除 `lib/`、`dist/`、`.build-matrix/` 等，避免脏缓存。

### 后台跑 + 看日志

```bash
bash scripts/run_bg.sh --name release-pi05 -- \
  bash scripts/release_bundle.sh --bundle pi05_libero --clean
bash scripts/run_bg.sh --name release-pi05 --tail
```

### 产物目录

```text
bundles/pi05_libero/dist/
├── flashcli-bundle.json
├── run.py
├── flash_rt/
├── runtime/
│   ├── sm89-cu124-linux-x86_64-py312/
│   │   └── flash_rt_*.so
│   └── sm89-cu130-linux-x86_64-py312/
│       └── flash_rt_*.so
└── ...
```

**不要**把 `build.sh`、`.build-matrix/`、开发 README 打进 zip（由 `RELEASE_PACK_FILES` 控制）。

---

## 7. 发布前 Checklist

- [ ] `flashcli bundle validate bundles/<name>` 通过
- [ ] `dist/runtime/` 含 manifest 声明的全部 env key
- [ ] `protocol_version` 与 `flashcli-bundle` 包一致
- [ ] 目标 GPU 上 `flashcli run` / `serve` smoke 通过
- [ ] `dist/` 无开发垃圾文件

---

## 8. 上传 FlashHub 与更新 catalog

1. 将 **`dist/` 整个目录**（或 zip 解压后的等价树）上传到 FlashHub。
2. 获得语义化 URL，例如：

   ```text
   https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero/1.0.3
   ```

3. 编辑 `src/flashcli/catalog/models.yaml`：

   ```yaml
   pi05_libero:
     description: ...
     bundle:
       repo: https://flashhub.../pi05_libero/1.0.3
   ```

4. Qwen 两个 preset **共用同一 `bundle.repo`**，用 `bundle_variant` 区分：

   ```yaml
   qwen3-8b-nvfp4:
     bundle_variant: qwen3
     bundle:
       repo: https://flashhub.../qwen_nvfp4/1.0.x

   qwen36-27b-nvfp4:
     bundle_variant: qwen36
     bundle:
       repo: https://flashhub.../qwen_nvfp4/1.0.x
   ```

5. 用户侧：`install.sh` 更新 flashcli 后，自动从新 `bundle.repo` sync。

---

## 9. 矩对照表

| 项目 | pi05_libero | qwen_nvfp4 |
|------|-------------|------------|
| SM | 89 | 120 |
| CUDA | 124 + 130 | **130 only** |
| python_abi | 312 | 312 |
| entry | run | run + serve |
| variants | 无 | qwen3 / qwen36 |
| Docker cu124 | 24.05-py3 | — |
| Docker cu130 | 25.10-py3 | 25.10-py3 |

细节：[runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)

---

## 10. 新增 Bundle 流程摘要

1. 复制 `bundles/pi05_libero/` 或 `qwen_nvfp4/` 目录结构。
2. 编写 `flashcli-bundle.json`（含 `protocol_version: 1`）与 `run.py` / `serve.py`。
3. 编写 `release-matrix.env`、`_bundle_build.sh`。
4. 本地 `build.sh` + `flashcli bundle validate` + smoke `run`/`serve`。
5. `release_bundle.sh --clean` → 上传 FlashHub。
6. **验证通过后** 才改 `models.yaml`。

---

## 11. 常见问题

| 现象 | 处理 |
|------|------|
| `protocol_version` 校验失败 | 升级主机 `pip install -e ./flashcli-bundle -e .`；manifest 写 `"protocol_version": 1` |
| 更新了 `models.yaml` 但 run 仍用旧 bundle | 看输出里的 `runtime_id` 与 `repo`；`flashcli doctor` / `flashcli models envs pi05_libero` 对比 catalog 与 cached repo。catalog 未生效时重装或设 `FLASHCLI_MODELS_YAML`。然后 `flashcli bundle sync PRESET --force` |
| bundle venv 缺 `flashcli_bundle` | 删 `~/.flashcli/runtimes/<id>/` 重跑；或 `flashcli run` 触发 venv 重建 |
| `pip install flashcli` 失败（缺 flashcli-bundle） | 确保 clone 的 repo 含 `flashcli-bundle/` 子目录；或用 `install.sh` |
| HF 权重失败 | `export HF_ENDPOINT=https://hf-mirror.com` 后 `flashcli pull` |
| pi05 在 SM120 上报错 | pi05 **仅 SM89**；Blackwell 用 qwen preset |
| qwen 在 cu124 上编译失败 | qwen **仅 cu130**；用 25.10-py3 容器 |

---

## 12. 相关文档

| 文档 | 内容 |
|------|------|
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | manifest 字段、options、variants |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 主机 CLI vs bundle venv vs flashcli-bundle |
| [environment.zh-CN.md](environment.zh-CN.md) | 环境变量 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | PR 规范 |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | 协议包 API |
