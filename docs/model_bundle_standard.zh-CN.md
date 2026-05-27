# flashcli 模型包标准（Model Bundle）

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

第三方通过 **Model Bundle** 交付：一份 **`flashcli-bundle.json`**、**`entry` 推理模块**、可选 **FlashRT `.so` / `flash_rt` Python**。flashcli **仅**加载 bundle 并调用 `entry`，**不**在 flashcli 源码中实现具体 Run/Serve 逻辑。

维护 flashcli 请参阅 [DEVELOPER.zh-CN.md](../codeplan/DEVELOPER.zh-CN.md)。**当前对外 catalog 仅 [`pi05_libero`](../src/flashcli/catalog/models.yaml)**；其他 `bundles/` 草稿在验证前不得写入 `models.yaml`。

每个 preset 在 **`models.yaml`** 中仅登记 **一个** bundle 源：顶层 **`bundle.zip` / `path` / `git`**。多环境 runtime 打在同一制品内（推荐：**单 zip + `lib/` 原生矩阵**）。详见 [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)。

## 目录布局

`{bundle_root}` 即运行时根（git checkout、`--bundle`、或 `~/.flashcli/bundles/...` 缓存）。除 `flashcli-bundle.json` 与 `entry` 指向的模块外，**无硬性子目录**。

```text
{bundle_root}/
├── flashcli-bundle.json    # 必须：entry、weights、python_dependencies、可选 native_matrix
├── run.py                  # 示例：entry.run.module = "run"
├── lib/                    # 可选（推荐）：带环境标签的 *.so（多环境矩阵）
├── flash_rt/               # 可选：FlashRT Python（官方包推荐；包内勿重复放 .so）
└── checkpoint/             # 可选：内嵌权重
```

**已发布参考（`pi05_libero`）** — 单个 CDN zip，内含 `lib/` 矩阵及：

```text
flashcli-bundle.json
run.py
_pi05_compat.py
flash_rt/
lib/
  flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py310.so
  flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py310.so
  ...（cu130、py311、py312 等）
```

**第三方**：可仅 `run.py` + `modules[].file` 声明的 `.so`，或完整 `lib/` 矩阵；`.so` **只发布一份**，路径在 manifest 中声明即可。

激活时 flashcli 将 **`bundle_root`** 加入 `PYTHONPATH`，安装 `python_dependencies`，并从 `lib/`（矩阵）或 `modules[]`（显式路径）加载原生扩展。

## 权重

在 `flashcli-bundle.json` 中声明（`models.yaml` **不**写权重）：

1. **包内**：`{bundle_root}/checkpoint/`（`weights_dir` 可改名）
2. **HuggingFace**：`weights.repo` / `revision`

解析顺序：

1. `--checkpoint`
2. 包内 `{weights_dir}/` 已有文件
3. `~/.flashcli/models/<preset>/checkpoint/`
4. 按 `weights` 从 HuggingFace 下载

## `flashcli-bundle.json`

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 2,
  "name": "my-model",
  "description": "可选说明",
  "weights_dir": "checkpoint",
  "capabilities": ["run", "serve"],
  "weights": {
    "source": "huggingface",
    "repo": "org/weights",
    "revision": "main"
  },
  "defaults": {},
  "serve": {},
  "post_pull": [{ "tokenizer": "paligemma" }],
  "entry": {
    "run": { "module": "run", "attr": "RunEngine" },
    "serve": { "module": "serve", "attr": "ServeEngine" }
  },
  "python": ">=3.10,<3.13",
  "python_abi": "310",
  "python_dependencies": {
    "torch": "torch",
    "pip": ["numpy", "transformers<4.56", "safetensors"],
    "optional_groups": { "server": ["fastapi", "uvicorn"] }
  },
  "cuda": {
    "cuda_tag": "124",
    "recommended_torch_index": "cu124"
  },
  "native_layout": "matrix",
  "native_matrix": ["sm89-cu124-linux-x86_64-py310"],
  "modules": [
    { "file": "flash_rt_kernels.so", "optional": false }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `format_version` | 必须为 `2`（扁平 bundle 根） |
| `capabilities` | `run`、`serve` |
| `entry.run` / `entry.serve` | 相对 **bundle 根** PYTHONPATH 的模块 + 类名 |
| `python_dependencies` | pip / torch |
| `python` / `python_abi` | 解释器约束；不匹配时在激活阶段快速失败 |
| `cuda` | `cuda_tag`、`recommended_torch_index` 等 |
| `native_layout` / `native_matrix` | `native_layout: matrix` 时从 `lib/` 按本机环境选带标签 `.so` |
| `modules` | 可选显式 `.so` 路径（相对 bundle 根）；无 `lib/` 矩阵时使用 |
| `weights` / `extra_weights` | 主/附加权重下载 |
| `defaults` / `serve` | 传给引擎的默认参数 |
| `post_pull` | 拉权重后步骤（tokenizer 等） |
| `requires.sm` | 可选：加载原生库时的 SM 白名单 |
| `build` / `native_libs` | 构建脚本写入的快照元数据 |

### 原生 `.so` 命名（`lib/` 矩阵）

带标签制品格式：

```text
{模块}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

示例：`flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

`flashcli run` 使用的环境键为 **`sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`**（含 Python ABI）。CUDA 仅在同一运行时大版本内模糊匹配（如 `cu124`↔`cu128`，**不会** `cu124`→`cu130`）。详见 [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)。

### 示例：Pi0.5 VLA（已发布 — `pi05_libero`）

```json
{
  "name": "pi05_libero",
  "config": "pi05",
  "framework": "torch",
  "capabilities": ["run"],
  "requires": { "sm": ["89", "120"] },
  "weights": {
    "source": "huggingface",
    "repo": "lerobot/pi05_libero_finetuned_v044",
    "revision": "main"
  },
  "post_pull": [{ "tokenizer": "paligemma" }],
  "entry": { "run": { "module": "run", "attr": "RunEngine" } },
  "python_dependencies": { "torch": "torch", "pip": ["numpy", "pillow", "..."] }
}
```

catalog 通过 `models.yaml` 的单个 `bundle.zip` 指向已组装制品；权重由 HF 拉取。维护者从源码构建见 [bundles/pi05_libero/README.zh-CN.md](../bundles/pi05_libero/README.zh-CN.md)。用户可用 `flashcli models envs pi05_libero` 查看本机环境键及 `lib/` 是否含匹配制品。

### 示例：同类多模型 — 单 runtime + catalog 多 preset（Qwen NVFP4）

工业上**同类模型共用一个 runtime 制品**（一份 `.so` + `flash_rt/`），差异只在权重与默认超参：

| 层 | 职责 |
|----|------|
| **bundle**（`flashcli-bundle.json`） | `variants.qwen3` / `variants.qwen36`：权重 repo、`weights_dir`、`serve` 默认、`env` |
| **catalog**（`models.yaml`） | 多个 preset 指向**同一** `bundle.path` 或 `bundle.zip`，用 **`bundle_variant`** 选型 |
| **CLI** | `--model` 仅覆盖 catalog（调试/临时切换） |

```yaml
# models.yaml — 两个产品 preset，一个 zip
qwen3-8b-nvfp4:
  bundle_variant: qwen3
  bundle:
    path: bundles/qwen_nvfp4   # 或 zip: https://.../flashcli-bundle-qwen-nvfp4-....zip

qwen36-27b-nvfp4:
  bundle_variant: qwen36
  bundle:
    path: bundles/qwen_nvfp4
```

```bash
flashcli run qwen3-8b-nvfp4 --prompt "你好"      # 自动 variant=qwen3
flashcli run qwen36-27b-nvfp4 --prompt "你好" --K 6
flashcli run qwen3-8b-nvfp4 --model qwen36 ...  # 临时覆盖（不推荐常态）
```

构建：[`bundles/qwen_nvfp4/build.sh`](../bundles/qwen_nvfp4/build.sh)（`--variant all`）。**验证通过前**可将 `bundle.path` 换为 `bundle.zip` 发布；勿为每个模型单独打 runtime zip。

## `entry` 入口约定

- `entry.*.module` 相对于 **bundle 根**（如 `run` → `run.py`）。
- 类实现 flashcli [`engines/base.py`](../src/flashcli/engines/base.py) 中的 `RunEngine` / `ServeEngine` 协议。
- 可 `from flashcli.bundle.activate import active_bundle` 读取 `defaults` / `serve`。
- 推理逻辑（`flash_rt`、`transformers`、裸 `.so` 算子等）**全部在 entry 模块内**。

## flashcli 推理协议（宿主侧）

bundle 内 entry 模块实现以下接口；flashcli `serve` 提供固定 HTTP 路由。

### RunEngine

| 方法 | 说明 |
|------|------|
| `load(checkpoint, preset, **opts)` | 加载模型 |
| `predict(prompt=, images=, **kwargs)` | 返回 `ndarray` 或 `dict` |

### ServeEngine

| 方法 | 说明 |
|------|------|
| `load(...)` | 加载模型 |
| `warmup(spec)` | 可选，如 `"32:128,128:256"` |
| `model_id` | `/v1/models` 返回的 id |
| `chat(request)` | 非流式 |
| `chat_stream(request)` | 流式 |

## Git bundle

**版本 = git ref**（branch / tag / commit）。每个 ref 对应本地：

```text
~/.flashcli/bundles/<preset>/refs/<sanitized_ref>/
~/.flashcli/bundles/<preset>/.flashcli_bundle.json
```

ref 优先级：`--bundle-ref` > `bundle.git.ref` > `refs[].default` > `main`。

flashcli 在仓库根或子树中定位 `flashcli-bundle.json`；**原生环境在运行时**由 `lib/` 或 `modules[]` 选择，**不再**按 git 仓内 `variants/<env>/` 子目录切换。

权重独立：`~/.flashcli/models/<preset>/checkpoint/`。

## `src/flashcli/catalog/models.yaml`

**仅** preset 名与 **每个 preset 一个** bundle 源（当前 `schema_version: 6`）。

```yaml
schema_version: 6

models:
  pi05_libero:
    description: Pi0.5 LIBERO — ...
    bundle:
      zip: https://cdn.example/.../flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
      # path: bundles/pi05_libero   # 本地调试（须含本机匹配的 lib/*.so）
      # git: { repo: "...", ref: main }
```

| 字段 | 说明 |
|------|------|
| `bundle.path` | 本地 bundle 目录（相对 flashcli 包根） |
| `bundle.git` | 远程仓 + 默认 ref |
| `bundle.zip` | 远程 URL 或本地 `.zip` |
| `bundle.refs` | 可选 git ref 白名单 |

**已移除 `bundle.variants`** — 不要在 catalog 里按环境登记多个 zip。多环境请打进同一 zip 的 `lib/` 矩阵（见 [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md)）。

Bundle 解析：`--bundle` > catalog 的 `zip` / `path` / `git` > 本地缓存 > 下载 / clone。

环境变量（`FLASHCLI_MODELS_YAML`、`FLASHCLI_HOME`、`HF_ENDPOINT` 等）见 [environment.zh-CN.md](environment.zh-CN.md)。

## 构建脚本（FlashRT 源码树，Linux GPU）

**矩阵发布（`pi05_libero` 推荐）：**

```bash
export FLASHRT_REPO=/path/to/FlashRT
export CUDA_HOME_CU124=/usr/local/cuda-12.4
bash scripts/build_pi05_release_matrix.sh --cuda-tag 124
# → bundles/pi05_libero/dist/flashcli-bundle-pi05-main-sm89-multi-linux-x86_64.zip
```

**单环境 bundle（维护者本地）：**

```bash
bash scripts/build_pi05_bundle.sh --bundle-dir flashcli/bundles/pi05_libero
bash scripts/build_pi05_bundle.sh --bundle-dir ... --pack-only
bash scripts/build_pi05_bundle.sh \
  --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
```

内部草稿 Qwen 包使用 `scripts/build_qwen_bundle.sh`（**SM120**）；验证通过前勿加入 catalog。见 [bundles/README.zh-CN.md](../bundles/README.zh-CN.md)。

## 最小交付清单

1. `flashcli-bundle.json`（`format_version: 2`，含 `entry`、`python_dependencies`、可选 `native_layout` / `modules` / `cuda`）
2. `entry` 指向的 Python 模块（如 `run.py` + `RunEngine`）
3. 可选：`lib/` 带标签 `.so` 矩阵 **或** `modules[].file` 列表
4. 可选：`flash_rt/` Python 树
5. 权重：`checkpoint/` 或 `weights.repo`

## 验证

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
# serve 类 bundle 在验证通过后：
# flashcli bundle install /path/to/bundle --profile serve
# flashcli serve <preset> --bundle /path/to/bundle --port 8000
```
