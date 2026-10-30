# flashcli Model Bundle 发布标准（format_version 4）

<p align="right"><a href="bundle_publish_standard.md">English</a> · <strong>简体中文</strong></p>

面向 **第三方 Bundle 构建方** 的对外规范：发布到 FlashHub 时 **必须** 满足的目录结构、`flashcli-bundle.json` 字段、entry 约定、构建溯源与 native 制品命名。

---

## 1. 概述

| 概念 | 说明 |
|------|------|
| **Model Bundle** | 一次发布的推理 runtime 制品：manifest + Python entry + 可选 `flash_rt/` + 按环境分包的 `.so` |
| **format_version** | 固定 **4** |
| **protocol_version** | `flashcli-bundle` 协议 API 版本，当前为 **1** |
| **权重** | **不** 打进 bundle；在 manifest 声明，由终端用户首次运行时拉取 |
| **版本** | 由 FlashHub ref（`flashcli-bundle/<name>:<version>`）固定，不使用版本文件 |
| **构建溯源** | 发布 manifest 的 `build.sources[]`（`name` + `source` + `commit`） |

**Python 与仅原生 bundle。** 常规 bundle 使用 `defaults.entry` 并携带 `flash_rt/` 树。**仅原生** bundle 把 `entry.kind` 设为 `native-abi` 或 `native-exec`（见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) §6–7）：**不带** Python entry、**不带** `flash_rt/`，C 库放在 `runtime/<runtime-dir>/substrate/`。

**v4 模型。** 一个 bundle = 一个模型 + 一个执行实现；平台差异放 `environments`。v4 不允许 `variants`、`backends`、`entries`；不同模型/后端拆成不同 bundle。

终端用户通过 inline ref（`flashcli-bundle/<name>:<version>`）获取 bundle。flashcli 先下载 `flashcli-bundle.json`，匹配宿主环境，再只下载对应的 `runtime/<runtime-dir>/`。

---

## 2. FlashHub 发布目录结构

上传 **整个发布树根目录**（保持相对路径不变）。FlashHub 语义化 API 返回 `data.files[]`，每项含 `download_url`、`file_name`、`file_size`、`md5_hash`；`download_url` 路径须与下表一致。

### 2.1 单环境（示例：pi05_libero）

```text
my_bundle/                              ← 上传根（版本目录内容）
├── flashcli-bundle.json                ← 必填；最先被拉取
├── run.py                              ← entry.run 模块
├── _pi05_compat.py                     ← bundle 内 helper（可选，随源码上传）
├── flash_rt/                           ← FlashRT Python 树（不含 .so）
│   ├── __init__.py
│   ├── api.py
│   └── …
└── runtime/
    └── sm120-cu130-linux-x86_64-py312/ ← env key = 目录名
        ├── flash_rt_kernels-{abi}-sm120-cu130-linux-x86_64-py312.so
        └── flash_rt_fa2-{abi}-sm120-cu130-linux-x86_64-py312.so
```

### 2.2 一个 bundle 多环境

`environments` 是唯一的平台矩阵；OS/GPU/CUDA/Python 差异放在 environments，不放在不同 ref。

```text
my_bundle/
├── flashcli-bundle.json
├── run.py
├── flash_rt/
└── runtime/
    ├── sm89-cu124-linux-x86_64-py312/
    │   ├── flash_rt_kernels-…-py312.so
    │   └── flash_rt_fa2-…-py312.so
    └── sm120-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-py312.so
        └── flash_rt_fa2-…-py312.so
```

### 2.3 发布包必须最小（强制）

发布树**必须最小**，不能只做到“没有 build 脚本”：

- 只包含 manifest、entry 模块/helper、entry 可达的 `flash_rt/` 模块，以及 `environments` 声明的 `runtime/<runtime-dir>/` 单元。
- `flash_rt/` 必须按依赖需要从 FlashRT 树 staging；不得携带无关模型、frontend、测试、reference、示例、文档、缓存或未使用的可选模块。
- 只有 manifest 声明的 option 或 environment 能触达的可选模块才允许保留；“以防万一”的文件不可发布。
- 当前环境发布只放当前一个 runtime 单元；完整矩阵只放 `environments` 列出的单元。

裁剪由 build/pack 负责：bundle build 脚本必须 staging 最小 `flash_rt/`，`pack` 只能复制 `RELEASE_PACK_FILES` + 选中的 runtime 单元。

### 2.4 不应出现在发布包中的内容

| 路径 / 文件 | 原因 |
|-------------|------|
| bundle 根目录下的 `flash_rt_*.so` | native 必须位于 `runtime/<runtime-dir>/` |
| `build.sh`、`.build-*`、测试、refs、示例、文档、缓存 | 非推理必需 |
| 未使用的 `flash_rt` 模型/frontend/backend 模块 | entry 不可达，增大发布包 |
| `flash_rt/` 内 `.so` / `.pyc` / `__pycache__` | `flash_rt/` 只放 Python 源码 |
| 模型权重 checkpoint | 由 manifest `weights` / `extra_weights` 声明外部拉取 |
| 顶层 `runtime`、`variants`、`backends`、`entries` | v4 使用 `environments`；这些字段不属于 v4 |

### 2.4 Preset ref（供集成方参考）

```text
flashcli-bundle/<name>:<version>
```

示例：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.5
flashcli run flashcli-bundle/qwen3_8b_nvfp4:1.0.0
```

- OS/GPU/CUDA/Python 由 host 从 `environments` 选择，**不** 写进 ref。
- 本地开发：`flashcli run bundles/<name>`（目录须含 `flashcli-bundle.json`）。

完整语法：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

---

## 3. `flashcli-bundle.json` 配置详解

### 3.0 作者 manifest 与生成物

**源码目录中的 `flashcli-bundle.json` 是权威、完整的作者文件**，由发布者手写并在 PR 中评审。build/pack/release **不得** 修改它。

生成物（不提交）：

| 文件 | 由谁写 | 内容 |
|------|--------|------|
| `.build/manifest-overlay.json` | `build.sh` / matrix finalize | 构建元数据：`build`、扫描出的 runtime 单元、`python_abi` |
| `dist/flashcli-bundle.json` | `pack.sh` | 可发布 manifest = 作者 manifest + 选中 runtime 映射 + `build` 溯源 |

脚本契约：

- **build / matrix cell** 可新增 tagged native 库（`lib/`，native-only 用 `runtime/<env>/substrate/`），可写 `.build/manifest-overlay.json`；**不得** 改 `flashcli-bundle.json`。
- **pack** 只读作者 manifest，把选中的 native 单元复制到 `runtime/`，合并 overlay 的 `build`，只写 `dist/flashcli-bundle.json`。
- **pack 默认** 只处理当前宿主环境；完整矩阵用 `--all-envs` / `--verify-matrix`。
- 终端用户与 FlashHub 消费 **`dist/flashcli-bundle.json`**，不是单独 overlay。

### 3.1 全局字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `format` | 是 | 固定 `"flashcli-model-bundle"` |
| `format_version` | 是 | 固定 **4** |
| `protocol_version` | 是 | 固定 **1**（与 flashcli 所带协议一致） |
| `name` | 是 | bundle 标识（仅描述）；与 FlashHub 仓库名一致只是可读性约定 |
| `description` | 建议 | 用户可读说明 |
| `defaults` | 是 | 所有环境共享的模型配置 |
| `environments` | 是 | 非空 env key → 平台覆盖；每项必须有 `runtime` |
| `build` | 生成 | FlashRT/构建溯源；由 pack 写入 `dist/` |
| `runtime_abi_version` | 条件 | `native-abi` 必填，固定 **1** |
| `exec_protocol_version` | 条件 | `native-exec` 必填，固定 **1** |
| `variants` / `backends` / `entries` | 禁止 | v4 一个模型一个实现；拆分 bundle |

### 3.2 `defaults.entry`

```json
"entry": {
  "run": {
    "kind": "python",
    "module": "run",
    "attr": "RunEngine"
  },
  "serve": {
    "kind": "python",
    "module": "serve",
    "attr": "ServeEngine"
  }
}
```

| 子字段 | 说明 |
|--------|------|
| `run` / `serve` | capability；`run` 启用 `flashcli run`，`serve` 启用 `flashcli serve` |
| `kind` | `python`（默认）、`native-exec`、`native-abi` |
| `module` | 相对 bundle 根的 Python 模块名（仅 Python） |
| `attr` | 类/可调用名（`RunEngine`/`ServeEngine` 或 script `main`） |
| `mode` | `engine`（默认）或 `script`（仅 Python） |

一个 capability 只能有一个实现。native 后端使用 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) 定义的 `native` 块。

### 3.3 `defaults.python_abi`

```json
"python_abi": "312"
```

- bundle venv 的 Python ABI，三位字符串。
- 必须与环境 key 的 `-py{PY}` 后缀一致。
- native-only bundle 省略；其 env key 无 Python 后缀。
- 仅当平台确实使用不同 ABI 时，environment 才覆盖它。

### 3.4 `defaults.python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": ["numpy", "safetensors", "transformers<4.56", "pillow"]
}
```

| 键 | 说明 |
|----|------|
| `torch` | PyTorch wheel；`index: "auto"` 按宿主 CUDA 选择 |
| `pip` | 额外 pip 包 |

environment 定义 `python_dependencies` 时整体替换 defaults。

### 3.5 `defaults.env`

engine 模式进入 entry 前注入的环境变量；值可用 `{models_dir}`、`{bundle_root}`。environment 的 `env` 按 map 合并覆盖 defaults。script 模式不应用 `defaults.env`，只接收 §4.5 的 `FLASHCLI_*`。

### 3.6 `defaults.weights`

```json
"weights": {
  "source": "huggingface",
  "repo": "lerobot/pi05_libero_finetuned_v044",
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "require_norm_stats": true
}
```

| 字段 | 说明 |
|------|------|
| `source` | `huggingface` 或 `modelscope` |
| `repo` / `revision` | 模型 id + **完整 40 位 commit SHA（发布强制）** |
| `allow_patterns` | 可选文件筛选；省略表示全量 |
| `require_norm_stats` | VLA 需要 norm stats 时设 `true` |
| `weights_dir` | 可选相对子目录；**默认不设置** |

`weights_dir` 不设置时，主权重使用共享 weights store 根目录。key 由 `source + repo + revision` 派生（可读目录 + hash），相同权重共享、不同 revision 不冲突。

**发布强制：** `weights.revision` 必须是不可变的完整 commit SHA；`main`、`master`、分支名和移动 tag 都不允许用于已发布 bundle。固定用于验证的那个 commit，保证缓存权重与发布 bundle 可复现。`extra_weights.*.revision` 同样适用。

新 v4 bundle 除非需要兼容旧布局，不要设 `weights_dir: "checkpoint"`。

### 3.7 `defaults.extra_weights`

```json
"extra_weights": {
  "tokenizer": {
    "source": "huggingface",
    "repo": "Qwen/Qwen3-1.7B",
    "revision": "0123456789abcdef",
    "allow_patterns": ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]
  }
}
```

| 字段 | 说明 |
|------|------|
| `source` / `repo` / `revision` | sidecar 仓库坐标；`revision` 必须是完整不可变 commit SHA |
| `allow_patterns` / `require_any_patterns` | 下载/就绪筛选 |
| `weights_dir` | 可选相对路径；**默认 `extra/<key>`**（相对主 weights store） |
| `require_norm_stats` | 可选就绪条件 |

`weights_dir` 必须是相对路径，不能含 `..`。

### 3.8 `defaults.run_options` / `defaults.serve_options`

这是 bundle 专用 CLI 默认值的唯一来源，`flashcli --help` 从此生成。

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Python keyword / CLI 名（snake_case） |
| `type` | 否 | `string`（默认）、`integer`、`float`、`boolean` |
| `default` | 否 | 用户省略时的值 |
| `help` | 是 | 帮助文本 |
| `phase` | 否 | run: `load`/`predict`；serve: `load`/`warmup` |
| `flag` | 否 | 长选项名；默认 `name` 的 `_` → `-` |

host 提供的 `--checkpoint`、`--host`、`--port` 不在这里声明。environment 可整体替换选项列表。

### 3.9 `environments`

```json
"environments": {
  "sm120-cu130-linux-x86_64-py312": {
    "runtime": "runtime/sm120-cu130-linux-x86_64-py312",
    "env": { "FLASHRT_PRECISION": "fp8" }
  }
}
```

| 子字段 | 必填 | 说明 |
|--------|------|------|
| `runtime` | 条件 | 共享 runtime 目录的相对路径；纯 Python/CPU 环境可省略，native entry 必填 |
| `match` | 仅 fallback | 多维 fallback 选择器（`os`、`arch`、`python_abi`，可选 `vendor`、`sm`、`cuda`） |
| `entry` | 否 | 平台 entry 覆盖 |
| `python_abi` | 否 | 平台 Python ABI 覆盖 |
| `python_dependencies` | 否 | 整体替换 defaults |
| `env` | 否 | map 合并覆盖 defaults |
| `weights` / `weights_dir` | 否 | 平台权重/布局 |
| `extra_weights` | 否 | 平台 sidecar |
| `run_options` / `serve_options` | 否 | 整体替换 |
| `post_pull` / `extra_pull` | 否 | 平台资源处理 |
| `runtime_abi_version` / `exec_protocol_version` | 否 | native 版本轴 |

没有 `match` 的条目是精确 env key。多个精确 env key 可以指向同一个 `runtime` 目录；该目录是无状态的。`runtime` 缺失/为空表示纯 Python（CPU fallback），不加载 native `.so`。

#### 3.9.1 fallback 匹配

```json
"nvidia-linux-py312": {
  "runtime": "runtime/rtx-fat-linux-py312",
  "match": {
    "os": "linux",
    "arch": "x86_64",
    "python_abi": "312",
    "vendor": "nvidia"
  }
},
"cpu-linux-py312": {
  "match": {
    "os": "linux",
    "arch": "x86_64",
    "python_abi": "312",
    "vendor": "cpu"
  }
}
```

- 精确 env key 优先。
- 只有没有精确 key 时才考虑 fallback。
- fallback 必须包含 `os`、`arch`、`python_abi`。
- 匹配维度越多优先级越高；没有 `priority` 字段。
- 同维度数且可能匹配同一 host 的两个 fallback 非法，必须在 `bundle validate`/`pack` 阶段失败。
- 互斥 fallback（如 `vendor: nvidia` 与 `vendor: amd`）允许。
- CPU fallback 可以省略 `runtime`。

### 3.10 构建溯源（这个 bundle 由哪些源码构建？）

发布 manifest 记录不可变的源码仓库列表，schema 可扩展到 FlashRT 之外的依赖：

```json
"build": {
  "sources": [
    {
      "name": "flashrt",
      "source": "https://github.com/flashrt-project/FlashRT.git",
      "commit": "66b18eb766e73e2fcad406bc622bd3bfd70664c1"
    },
    {
      "name": "wan",
      "source": "https://github.com/Wan-Video/Wan2.2.git",
      "commit": "0123456789abcdef0123456789abcdef01234567"
    }
  ]
}
```

- `name`：稳定标识（`flashrt`、`flashrt-nexus`、`wan` 等）；`source`：仓库 URL；`commit`：完整 40 位 commit SHA。
- 所有参与生成 Python/runtime 产物的源码都要列出；使用 FlashRT 构建的 bundle 必须包含 `flashrt`。
- 同一 bundle 的所有 `environments` 必须使用相同的 `build.sources`。如果某个 runtime 单元需要不同来源/commit，拆成独立 bundle。
- **不要**把 `runtime_version`、`build_id`、`target`、`features`、`native_artifact_tag`、tag 等生成细节写进发布 manifest；这些只保留在维护者侧的 `.build/manifest-overlay.json`。
- `pack` 从 overlay 生成这个最小对象；旧 overlay 没有 `sources` 时，用 overlay/`git remote get-url origin` + `git rev-parse HEAD` 合成 `flashrt`。
- 可读 `dist/flashcli-bundle.json` 或运行 `flashcli models show <ref>`。
- `flash_rt/BUNDLE_VERSION` / `substrate/VERSION` 仍是 bundle 自有诊断，不能替代 `build`。

### 3.11 完整示例

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 4,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 LIBERO VLA",
  "build": {
    "sources": [
      {
        "name": "flashrt",
        "source": "https://github.com/flashrt-project/FlashRT.git",
        "commit": "66b18eb766e73e2fcad406bc622bd3bfd70664c1"
      }
    ]
  },
  "defaults": {
    "entry": { "run": { "module": "run", "attr": "main", "mode": "script" } },
    "python_abi": "312",
    "python_dependencies": {
      "torch": { "package": "torch", "index": "auto" },
      "pip": ["numpy", "pyyaml", "safetensors", "pillow"]
    },
    "run_options": [
      { "name": "prompt", "type": "string", "help": "Task instruction.", "phase": "predict" }
    ],
    "weights": {
      "source": "modelscope",
      "repo": "lerobot/pi05_libero_finetuned_v044",
      "revision": "0123456789abcdef0123456789abcdef01234567",
      "require_norm_stats": true
    }
  },
  "environments": {
    "sm120-cu130-linux-x86_64-py312": {
      "runtime": "runtime/sm120-cu130-linux-x86_64-py312"
    }
  }
}
```

---

## 4. Entry 规则

### 4.1 模块位置与 import

- `entry.*.module` 对应 bundle 根下的 `{module}.py`（或包目录）。
- bundle 根会加入 `sys.path`；entry 与同目录 helper 可直接互相 import。
- entry 只能依赖 **`flashcli_bundle`**；不要 `import flashcli`（CLI 包）。

### 4.2 Native `.so` 加载

调用 entry 前，flashcli：

1. 从选中的 environment 找到 `runtime/<runtime-dir>/`。
2. 把其中 `.so` 注册为扩展模块（导入名如 `flash_rt_kernels`、`flash_rt_fa2`，不带 env 后缀）。
3. 把 bundle 根加入 `sys.path`，使 `import flash_rt` 和本地 helper 可用。

script 模式不得通过环境变量或手动 `dlopen` 加载 `.so`。

### 4.3 Engine 模式

`RunEngine.load(checkpoint, preset, **options)` 加载权重；`RunEngine.predict(...)` 推理。`ServeEngine` 提供 `model_id`、`load`、`warmup`、`chat`、`chat_stream`。默认值从 manifest 读取，不要在代码里重复。

### 4.4 Script 模式

`def main(argv: list[str] | None = None) -> int | None` 接收 bundle 参数；权重从环境变量读取。script 模式下 `run_options`/`serve_options` 仅用于帮助文档。

### 4.5 Entry 环境变量

| 变量 | 模式 | 说明 |
|------|------|------|
| `FLASHCLI_CHECKPOINT` | script | 主权重绝对路径 |
| `FLASHCLI_BUNDLE_ROOT` | script | bundle 根绝对路径 |
| `FLASHCLI_PRESET` | script | preset ref 字符串 |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | script | `extra_weights.<key>` 绝对路径 |
| manifest `env` / `defaults.env` | engine | 作者定义；支持 `{models_dir}`、`{bundle_root}` |

不要依赖 `FLASHCLI_RUNTIME_ID`、`FLASHCLI_IN_BUNDLE_VENV` 或 host 路径配置等内部变量。

### 4.6 文件对应关系

| manifest | 发布包内文件 |
|----------|----------------|
| `entry.run.module: "run"` | `run.py`，含 `RunEngine` 或 `main` |
| `entry.serve.module: "serve"` | `serve.py`，含 `ServeEngine` 或 `main` |
| 两者兼有 | 两个文件都必须存在 |

---

## 5. Native `.so` 目录与命名

### 5.1 环境键

```text
{platform_tail}-{os}-{arch}-py{PY}
```

| 段 | 含义 | 示例 |
|----|------|------|
| `platform_tail` | 不透明平台/运行时标识 | `sm120-cu130` |
| `os` | OS | `linux` |
| `arch` | CPU 架构 | `x86_64` |
| `PY` | Python ABI | `312` |

native-only bundle 省略 `-py{PY}`。允许非 NVIDIA platform_tail（如 `gfx942-rocm611`）。

### 5.2 目录规则

1. native `.so` 位于 `runtime/<dir>/` 等 runtime 目录；目录名任意。
2. 多个 environment 可以指向同一个 runtime 目录并共享同一批 `.so`。
3. 禁止在 bundle 根或 `lib/` 下放 `.so`。
4. `flash_rt/` 只放 Python 源码，不含 `.so`、`.pyc`、`__pycache__`。
5. sync 时只下载选中的 runtime 目录一次，以及共享源码树。
6. 无 runtime 的 Python 环境不需要 `flash_rt/`，除非 entry 显式 import。

### 5.3 文件名规则

```text
{module_base}-{flashrt_abi}-{build_tag}.so
```

- `module_base`：逻辑导入名（`flash_rt_kernels`、`flash_rt_fa2` 等），必须有。
- `flashrt_abi`：构建标识。
- `build_tag`：任意可读 tag，不必等于任何 env key。
- 每个 module 每个 runtime 目录建议只放一个 artifact。host 扫描选中目录下可识别的 native extension `.so`，不把文件名绑定到 env key。
- 允许 fat binary（多 SM 架构/PTX）；兼容性由发布方负责。

### 5.4 矩阵说明

- 每个 `(SM, CUDA, python_abi)` 组合对应一个 environment key。
- 各单元应暴露相同的 `module_base` 集合，除非平台确实不同。
- 发布可以是当前单环境或完整矩阵，但 manifest `environments` 必须与上传的 `runtime/` 目录严格一致。

---

## 6. 发布前自检清单

- [ ] `format_version: 4`、`protocol_version: 1`
- [ ] `defaults` 非空；`environments` 非空
- [ ] 每个 native environment 都有 `runtime`；纯 Python/CPU 环境可省略
- [ ] 无 `variants`、`backends`、`entries`、顶层 `runtime`
- [ ] native entry：按 `kind` 精确设置 `runtime_abi_version` / `exec_protocol_version`
- [ ] `flashcli-bundle.json` 位于发布根目录
- [ ] 每个 Python `entry.*.module` 都有文件与符号
- [ ] Python entry 有 `python_abi` + `python_dependencies`；env key 带 `-py` 后缀时必须与 `python_abi` 一致
- [ ] 每个非空 `environments.<key>.runtime` 都有目录，且含至少一个可识别 native `.so`（native-only 可为 `substrate/*.so`）
- [ ] 共享 runtime 目录的 environments 兼容；fallback 无歧义
- [ ] bundle 根、`lib/`、`flash_rt/` 内无 stray `.so`
- [ ] Python entry 在有 native runtime 时带 `flash_rt/`；无 runtime 的 CPU 环境和 native-only bundle 可不带
- [ ] `dist/flashcli-bundle.json` 有 `build.sources[]`（`name` + `source` + `commit`）；所有 environment 使用同一组 sources
- [ ] 所有 `weights` / `extra_weights` 的 revision 都是完整不可变 commit SHA（禁止 `main`/`master`/分支/tag）
- [ ] `flashcli bundle validate` 通过
- [ ] 在目标 GPU 上 smoke `flashcli run` / `serve`
- [ ] `dist/` 最小：无开发文件、测试、refs、缓存、未使用的模型/frontend 模块、权重
- [ ] `flash_rt/` 只含 entry 与 manifest 声明的 option 可触达的模块
- [ ] 上传后 `bundle.repo` 返回完整 `files[]`（含子目录 `.so` URL）

---

## 7. 相关文档

| 文档 | 内容 |
|------|------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | 英文版 |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | ref 与终端用户运行时流程 |
| [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) | native entry 契约 |
| [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) | 维护者构建/发布流程 |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
