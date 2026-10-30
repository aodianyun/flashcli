# Bundle 构建与发布指南

<p align="right"><a href="bundle_builder_guide.md">English</a> · <strong>简体中文</strong></p>

> **维护者文档。** 入口：[CONTRIBUTING.md](../CONTRIBUTING.md)；文档索引：[docs/README.zh-CN.md](README.zh-CN.md)。

面向 **Model Bundle 维护者（内部）**：环境安装、本地开发、矩阵编译、打包校验、FlashHub 上传与 ref 文档更新。

**对外 Bundle 发布标准**（manifest / entry / `.so` / FlashHub 目录，不含脚本）→ **[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)**  

格式摘要见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)；终端用户命令见各 bundle 的 `README.zh-CN.md`；构建流程见 `BUILD.zh-CN.md`。

---

## 1. 你要做什么

| 角色 | 目标 | 需要装什么 |
|------|------|------------|
| **Bundle 构建者** | 改 `run.py` / `flashcli-bundle.json`，编译 FlashRT，发布到 FlashHub | `./install.sh --from-source`（Go host）+ `pip install -e ./flashcli-bundle` + FlashRT + Docker/GPU |
| **终端用户** | `flashcli run <ref>` | `install.sh` / `auto_install.sh`（Go 二进制；bundle venv 按需装 `flashcli-bundle[infer]`） |

Bundle **entry 代码只 import `flashcli_bundle`**，不要 import `flashcli` CLI 包：

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.protocol import ChatRequest, RunEngine
from flashcli_bundle.preset import Preset
```

**仅原生** bundle 没有 Python entry（见 §5）。

---

## 2. 推荐环境（含镜像）

### 硬件

| Bundle | GPU | CUDA 用户态 | 说明 |
|--------|-----|-------------|------|
| `pi05_libero` | **SM89**（Ada）、**SM120**（Blackwell） | cu124（SM89）· cu130 | SM120 用 `sm120-cu130` 单元 |
| `higgs_audio` | **SM120**（Blackwell） | **仅 cu130** | Python 3.10 |

### 软件

- **OS**：Linux x86_64
- **Docker + NVIDIA Container Toolkit**（矩阵发布默认走容器）
- **Go ≥ 1.24**（主机 CLI）；bundle venv 按 manifest 的 `python_abi` 固定

### 国内 / 受限网络（推荐）

```bash
# 1) 安装 flashcli（Gitee + pip/HF 镜像）
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror

# 2) 或从源码构建（需 Go/git；脚本会自动安装）
curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --from-source

# 3) Hugging Face 权重镜像（pull/run 前）
export HF_ENDPOINT=https://hf-mirror.com

# 4) bundle venv 的 pip 镜像（装入 torch/依赖时）
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
export PIP_TRUSTED_HOST=mirrors.aliyun.com
```

Qwen 矩阵容器镜像：`nvcr.io/nvidia/pytorch:25.10-py3`（见各 bundle 的 `release-matrix.env`）。

---

## 3. 工作区布局

```text
workspace/
├── flashcli/                 # git clone 本仓库
│   ├── flashcli-bundle/      # 协议 + infer 包（与 flashcli 同 repo）
│   ├── go/                    # 主机 CLI（Go 二进制）
│   ├── bundles/
│   │   ├── pi05_libero/
│   │   └── higgs_audio/
│   ├── scripts/
│   │   └── release_bundle.sh
└── FlashRT/                  # 推理内核（release 脚本可自动 clone）
```

```bash
git clone https://gitee.com/aodiansoft/flashcli.git   # 或 GitHub
cd flashcli

# 开发安装（构建者必做）
pip install -e ./flashcli-bundle

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
├── runtime/                  # pack 后：runtime/<runtime-dir>/*.so
├── release-matrix.env        # 发布矩阵（SM、CUDA、py ABI）
├── _bundle_build.sh          # cmake + 编译逻辑
├── build.sh                  # 本地单环境 build
├── release.sh                # → scripts/release_bundle.sh
└── dist/                     # 发布产物（上传 FlashHub）
```

**仅原生** bundle（`entry.kind = native-abi|native-exec`）省略 `run.py` / `flash_rt/`，C 库放在 `runtime/<runtime-dir>/substrate/`。

### manifest 必填要点（format_version 4）

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 4,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 LIBERO VLA",
  "defaults": {
    "entry": { "run": { "module": "run", "attr": "RunEngine" } },
    "python_abi": "312",
    "run_options": [ ... ],
    "python_dependencies": {
      "torch": { "package": "torch", "index": "auto" }
    },
    "weights": { "source": "huggingface", "repo": "org/model", "revision": "0123456789abcdef0123456789abcdef01234567" }
  },
  "environments": {
    "sm89-cu124-linux-x86_64-py312": {
      "runtime": "runtime/sm89-cu124-linux-x86_64-py312"
    }
  }
}
```

- **`defaults` / `environments`**：均必填。
- native environment 必须有 `runtime`；Python/CPU environment 可省略。
- 多个 environment 可指向同一 runtime 目录。fallback 用 `match`（无 `priority`）；同维度且可重叠的 fallback 会在 `bundle validate` 失败。
- **`protocol_version`**：必须与已安装 `flashcli-bundle` 的 `PROTOCOL_VERSION` 一致（当前为 **1**）。
- 一个 bundle = 一个模型 + 一个实现；不要用 `variants`、`backends`、`entries`，拆成不同 bundle。
- **`run_options` / `serve_options`**：CLI 参数与默认值唯一来源；`run.py` 用 `run_option_defaults()`，勿写死字面量。
- native kind 增加 `runtime_abi_version` / `exec_protocol_version` 与 `native` 块（见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)）。
- 发布后的 `dist/flashcli-bundle.json` 还带生成的 `build.sources[]`；`flashcli models show <ref>` 会打印。
- 所有 `weights` / `extra_weights` 的 revision 必须固定为完整 commit SHA；禁止发布 `main`/`master`/分支/tag。

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

**仅原生** bundle：构建 Python-free 的 C 库（如 FA2 raw → `flashrt_exec`/producer → Nexus），stage 到 `runtime/<runtime-dir>/substrate/`。

### 步骤 B — 校验 manifest 与 layout

```bash
export BUNDLE="$(pwd)/bundles/pi05_libero"
flashcli bundle validate "$BUNDLE"
```

**做什么**：检查 `flashcli-bundle.json`、entry 文件、`run_options` 布局、`protocol_version`、本机 env 的 native ABI（若 `--probe-abi`）。

### 步骤 C — 拉权重 + smoke run

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 内网推荐

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the red block" \
  --image /path/to/base.jpg

flashcli run "$BUNDLE" --help    # 查看 manifest run_options
```

**做什么**：主机 CLI sync → 建 bundle venv（按 manifest 的 `python_abi`）→ 装 torch + **flashcli-bundle** → re-exec → 执行你的 `run.py`。

v4 serve 本地测：

```bash
export BUNDLE="$(pwd)/bundles/qwen3_vl_8b_nvfp4"
flashcli serve "$BUNDLE" --host 127.0.0.1 --port 8000
flashcli serve "$BUNDLE" --help
```

---

## 6. 正式发布流水线（逐步说明）

**一条命令**（在 `flashcli` 仓库根目录）默认只构建并打包**当前宿主环境**：

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --clean
# 或
bash scripts/release_bundle.sh --bundle higgs_audio --clean
```

等价于进入 `bundles/<name>/` 执行 `bash release.sh --clean`。脚本调用 bundle 的 `build.sh`，然后只 pack 当前 `runtime/<runtime-dir>/` 单元。完整 Docker/多 CUDA 矩阵需显式加 `--matrix`。

### 脚本内部阶段

| 阶段 | 做什么 | 产出 |
|------|--------|------|
| **1. 读 `release-matrix.env`** | 确定 SM、CUDA tags、Python ABI、Docker 镜像、打包文件列表 | 矩阵维度 |
| **2. 确保 FlashRT** | clone/update `../FlashRT`（可 `export FLASHRT_REPO=` 覆盖） | 源码 |
| **3. 当前环境 build** | `build.sh`（`--matrix` 时走 `_bundle_build.sh`） | 当前 env `.so` |
| **4. 写入 `runtime/`** | 当前 env 的 `runtime/<runtime-dir>/` | native 制品 |
| **5. `pack_bundle.sh`** | 复制 entry、当前 runtime 单元、刷新 manifest | `dist/` 源码树 |
| **6. 校验** | ABI / layout / manifest options / protocol | 失败则 exit |

完整矩阵（显式 opt-in）：

```bash
bash scripts/release_bundle.sh --bundle pi05_libero --matrix --clean
```

`--clean`：删除 `lib/`、`dist/`、`.build-matrix/` 等，避免脏缓存。`pack.sh` 也支持 `--all-envs` / `--verify-matrix` 做完整矩阵打包。

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

**`dist/` 必须最小**：不要把 `build.sh`、`.build-*`、测试、refs、缓存或未使用的 FlashRT 模型/frontend 打进包。build 脚本必须 staging 最小 `flash_rt/`；`pack` 只复制 `RELEASE_PACK_FILES` + 选中的 runtime 单元。

---

## 7. 发布前 Checklist

- [ ] `flashcli bundle validate bundles/<name>` 通过
- [ ] `dist/runtime/` 含 manifest 声明的全部 env key
- [ ] `protocol_version` 与 `flashcli-bundle` 包一致
- [ ] 目标 GPU 上 `flashcli run` / `serve` smoke 通过
- [ ] `dist/` 无开发垃圾文件

---

## 8. 上传 FlashHub 与告知用户 ref

1. 将 **`dist/` 整个目录**上传到 FlashHub。
2. 获得语义化 URL，例如：

   ```text
   https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.5
   ```

3. 在 README / BUILD 中更新固定 ref：
   - 例如：`flashcli-bundle/pi05_libero:1.0.5`

4. 用户侧：安装/升级 flashcli 后，执行 `flashcli run <ref>` 或 `flashcli bundle sync <ref>` 从新版本 sync。

---

## 9. 矩对照表

| 项目 | pi05_libero | higgs_audio |
|------|-------------|------------|
| SM | 89 | 120 |
| CUDA | 124 + 130 | **仅 130** |
| python_abi | 312 | 310 |
| entry | run | run |
| Docker cu124 | 24.05-py3 | — |
| Docker cu130 | 25.10-py3 | 25.10-py3 |

细节：[runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)

---

## 10. 新增 Bundle 流程摘要

1. 复制 `bundles/pi05_libero/` 或 `higgs_audio/` 目录结构。
2. 编写 `flashcli-bundle.json`（含 `protocol_version: 1`）与 `run.py` / `serve.py`。
3. 编写 `release-matrix.env`、`_bundle_build.sh`。
4. 本地 `build.sh` + `flashcli bundle validate` + smoke `run`/`serve`。
5. `release_bundle.sh --clean` → 上传 FlashHub → 更新文档中的 pinned ref。


### 10.1 Bundle README / BUILD 规范

每个 bundle 目录必须包含中英文两对文档：

- `README.md` / `README.zh-CN.md`：面向 FlashHub 用户。
- `BUILD.md` / `BUILD.zh-CN.md`：面向维护者。

`README` 结构（以 `bundles/pi05_libero/README.zh-CN.md` 为参考）：

1. `# <模型显示名>`。
2. 语言切换（`English · 简体中文`）。
3. 简短模型说明与能力。
4. 元数据表：`Ref`、`权重`、`GPU`、`CUDA`、`Python`、`能力`。
5. 输入 / 输出、权重下载说明。
6. `## 运行`，使用真实命令和固定 ref。
7. 有 `entry.serve` 时增加 `## 服务`。
8. `## 参数`，内容来自 manifest 的 `run_options` / `serve_options`。
9. 链接到 `BUILD.zh-CN.md`。

`BUILD` 结构：

1. `# <bundle> — 构建与冒烟测试`。
2. 语言切换。
3. 维护者流程摘要和 `要求`。
4. Host / FlashRT 准备。
5. `## 1. 编译`，给出准确 `build.sh` 命令和输出。
6. `## 2. 打包`，说明 `pack.sh` / `pack_bundle.sh` 产物。
7. `## 3. 校验`。
8. `## 4. 冒烟测试`，给出真实 `run` / `serve` 命令。
9. `## 5. 发布`，给出固定 FlashHub ref。
10. 故障排查表。

规则：

- 文档只描述 **v4 manifest**（`defaults` / `environments`）。
- ref、默认值必须与 `flashcli-bundle.json` 一致。
- 不写 `@variant`、v3 `runtime` map 或过期本地路径。
- `README` 不写编译实现；编译细节只放 `BUILD`。
- 中英文结构保持一致。

---

## 11. 常见问题

| 现象 | 处理 |
|------|------|
| `protocol_version` 校验失败 | 升级主机 `pip install -e ./flashcli-bundle`；manifest 写 `"protocol_version": 1` |
| run 仍用旧 bundle | 看输出里的 `runtime_id` 与 `repo`；`flashcli doctor` / `flashcli models show <ref>` 对比 cached repo。然后 `flashcli bundle sync <ref> --force` |
| bundle venv 缺 `flashcli_bundle` | 删 `~/.flashcli/runtimes/<id>/` 重跑；或 `flashcli run` 触发 venv 重建 |
| bundle venv 缺 `flashcli-bundle` | 设 `FLASHCLI_BUNDLE_PIP_SPEC=/path/to/flashcli-bundle[infer]` 或 `~/.flashcli/install.env` 的 `FLASHCLI_INSTALL_REPO/REF`；**勿**在 bundle venv 内 `pip install flashcli` |
| HF 权重失败 | `export HF_ENDPOINT=https://hf-mirror.com` 后 `flashcli pull` |
| pi05 `NativeEnvironmentNotSupportedError` | 确认 manifest 含本机 env key（含 `sm120-cu130`）；`flashcli bundle sync flashcli-bundle/pi05_libero:1.0.5 --force` |
| qwen 在 cu124 上编译失败 | qwen **仅 cu130**；用 25.10-py3 容器 |

---

## 12. 相关文档

| 文档 | 内容 |
|------|------|
| [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) | **对外**发布标准：manifest、entry、.so、FlashHub 目录 |
| [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) | `entry.kind` 后端与原生契约 |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | preset ref 语法 + 运行时流程 |
| [architecture.zh-CN.md](architecture.zh-CN.md) | 主机 CLI vs bundle venv vs flashcli-bundle |
| [environment.zh-CN.md](environment.zh-CN.md) | 环境变量 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | PR 规范 |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | 协议包 API |
