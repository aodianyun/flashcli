# flashcli Model Bundle 发布标准（format_version 3）

<p align="right"><a href="bundle_publish_standard.md">English</a> · <strong>简体中文</strong></p>

面向 **第三方 Bundle 构建方** 的对外规范：说明发布到 FlashHub 时 **必须** 满足的目录结构、`flashcli-bundle.json` 字段、entry 约定与 native 制品命名。  

---

## 1. 概述

| 概念 | 说明 |
|------|------|
| **Model Bundle** | 一次发布的推理 runtime 制品：manifest + Python entry + 可选 `flash_rt/` + 按环境分包的 `.so` |
| **format_version** | 当前唯一支持 **3** |
| **protocol_version** | `flashcli-bundle` 协议 API 版本，当前为 **1** |
| **权重** | **不** 打进 bundle；在 manifest 中声明 Hugging Face 等来源，由终端用户首次运行时拉取 |

终端用户通过 catalog 中的 `bundle.repo` URL 获取 bundle；flashcli 先下载 `flashcli-bundle.json`，再按本机 GPU/CUDA/Python 匹配 `runtime` 中的 env key，仅下载对应 `runtime/<env-key>/` 下的文件。

---

## 2. FlashHub 发布目录结构

上传 **整个发布树根目录**（保持相对路径不变）。FlashHub 语义化 API 返回 `data.files[]`，每项含 `download_url`、`file_name`、`file_size`、`md5_hash`；`download_url` 路径须与下表一致。

### 2.1 单 preset（示例：pi05_libero）

```text
my_bundle/                              ← 上传根（版本目录内容）
├── flashcli-bundle.json                ← 必填；最先被拉取
├── run.py                              ← entry.run 模块
├── _pi05_compat.py                     ← bundle 内 helper（可选，随源码一并上传）
├── flash_rt/                           ← FlashRT Python 树（不含 .so）
│   ├── __init__.py
│   ├── api.py
│   └── …
└── runtime/
    ├── sm89-cu124-linux-x86_64-py312/  ← env key = 目录名
    │   ├── flash_rt_kernels-{abi}-sm89-cu124-linux-x86_64-py312.so
    │   └── flash_rt_fa2-{abi}-sm89-cu124-linux-x86_64-py312.so
    └── sm89-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-sm89-cu130-linux-x86_64-py312.so
        └── flash_rt_fa2-…-sm89-cu130-linux-x86_64-py312.so
```

### 2.2 多 preset 共用 repo（示例：qwen_nvfp4）

同一 repo 内 **`entry` 相同**，通过 catalog 的 `bundle_variant` 选择 variant 块中的权重与 options：

```text
qwen_nvfp4/
├── flashcli-bundle.json
├── run.py
├── serve.py                            ← entry.serve 存在时必填
├── _qwen_util.py
├── _backend_qwen3.py
├── _backend_qwen36_agent.py
├── …                                   ← entry 依赖的 Python 模块
├── flash_rt/
│   └── …
└── runtime/
    └── sm120-cu130-linux-x86_64-py312/
        ├── flash_rt_kernels-…-sm120-cu130-linux-x86_64-py312.so
        ├── flash_rt_fa2-…-sm120-cu130-linux-x86_64-py312.so
        └── flash_rt_fp4-…-sm120-cu130-linux-x86_64-py312.so   ← NVFP4 等场景按需
```

### 2.3 不应出现在发布包中的内容

| 路径 / 文件 | 原因 |
|-------------|------|
| bundle 根目录下的 `flash_rt_*.so` | native 必须位于 `runtime/<env-key>/` |
| `build.sh`、`.build-matrix/`、`dist/` 打包脚本产物以外的开发垃圾 | 非 runtime 必需 |
| 模型权重 checkpoint | 由 manifest `weights` / variant `weights` 声明外部拉取 |

### 2.4 catalog 对接（供集成方参考）

```yaml
models:
  my-preset:
    bundle:
      repo: https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/my_model/1.0.0
  qwen3-8b-nvfp4:
    bundle_variant: qwen3          # 对应 manifest variants.qwen3
    bundle:
      repo: https://flashhub…/qwen_nvfp4/1.0.1
```

- **`bundle.repo`**：FlashHub 仓库地址 URL。
- **`bundle_variant`**：仅当 manifest 含 `variants` 时使用；多个 preset 可共用同一 `repo`。

---

## 3. `flashcli-bundle.json` 配置详解

### 3.1 顶层必填与推荐字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `format` | 是 | 固定 `"flashcli-model-bundle"` |
| `format_version` | 是 | 固定 **3** |
| `protocol_version` | 是 | 固定 **1**（与 flashcli 所带 `flashcli-bundle` 协议一致） |
| `name` | 是 | bundle 标识，与目录/FlashHub repo 名一致为佳 |
| `description` | 推荐 | 人类可读说明 |
| `python_abi` | 是 | bundle 固定 Python ABI，三位数字字符串，如 `"312"` = CPython 3.12 |
| `entry` | 是 | 至少含 `run` 或 `serve` 之一（见 §4） |
| `runtime` | 是 | env key → 相对路径映射（见 §5） |
| `python_dependencies` | 是 | bundle venv 内 pip 依赖（见 §3.4） |
| `run_options` | 条件 | 无 `variants` 且支持 `run` 时必填 |
| `serve_options` | 条件 | 无 `variants` 且支持 `serve` 时必填 |
| `weights` | 条件 | 单 preset bundle 的权重来源 |
| `variants` | 条件 | 多 preset 共用 repo 时必填（见 §3.3） |
| `default_variant` | 推荐 | 存在 `variants` 时的默认 variant 名 |
| `post_pull` | 否 | 权重拉取后的钩子（如 tokenizer 准备） |

### 3.2 `entry`

```json
"entry": {
  "run":  { "module": "run",  "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

| 子字段 | 说明 |
|--------|------|
| `module` | 相对 bundle 根的 Python 模块名（不含 `.py`），如 `"run"` → `run.py` |
| `attr` | 模块内暴露的类名，须实现对应协议（见 §4） |

能力由 `entry` 推断：有 `run` 即支持 `flashcli run`；有 `serve` 即支持 `flashcli serve`。

### 3.3 `variants`（多 preset 共用同一 repo）

存在 `variants` 时：

- **禁止** 顶层 `run_options` / `serve_options` / `weights`（校验报错）。
- **每个 variant** 必须自带完整的 `run_options`、`serve_options`（若该 variant 需要对应能力）、`weights` 等。

variant 块常用字段：

| 字段 | 说明 |
|------|------|
| `description` | variant 说明 |
| `weights_dir` | 权重在本地 cache 下的子目录名（相对 preset） |
| `weights` | `{ "source": "huggingface", "repo": "…", "revision": "…" }` |
| `extra_weights` | 附加权重（如 Qwen MTP），结构同 weights，可加 `cache_name`、`allow_patterns` |
| `env` | 激活 bundle 时写入进程环境，支持 `{models_dir}`、`{bundle_root}` 占位符 |
| `run_options` / `serve_options` | 该 variant 专属 CLI 参数（结构见 §3.5） |

### 3.4 `python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": [
    "numpy",
    "safetensors",
    "transformers<4.56"
  ]
}
```

| 键 | 说明 |
|----|------|
| `torch` | PyTorch wheel；`index: "auto"` 表示由 flashcli 按本机 CUDA 线选择 cu124/cu128 索引（**推荐**） |
| `pip` | 其余 pip 包列表（字符串，可带版本约束） |

bundle venv 的 Python 版本由 `python_abi` 决定，与主机 CLI Python 版本无关。

### 3.5 `weights`（单 preset 或 variant 内）

```json
"weights": {
  "source": "huggingface",
  "repo": "lerobot/pi05_libero_finetuned_v044",
  "revision": "main",
  "require_norm_stats": true
}
```

| 字段 | 说明 |
|------|------|
| `source` | 当前支持 `"huggingface"` |
| `repo` / `revision` | Hugging Face 模型 id 与分支/提交 |
| `require_norm_stats` | 可选；VLA 等需 norm stats 时为 `true` |

### 3.6 `run_options` / `serve_options`

Bundle 自定义 CLI 参数的 **唯一** 默认值来源；终端 `--help` 由 manifest 生成。

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 传入 engine 的 Python 关键字参数名（snake_case） |
| `type` | 否 | `string`（默认）、`integer`、`float`、`boolean` |
| `default` | 否 | 用户省略该 flag 时的默认值 |
| `help` | 是 | 帮助文本 |
| `phase` | 否 | **run**：`load`（传给 `load()`）或 `predict`（传给 `predict()`）；**serve**：`load` 或 `warmup` |
| `flag` | 否 | CLI 长选项名（不含 `--`）；默认 `name` 的 `_` 转为 `-` |

**不在 manifest 中声明的参数**（由 flashcli 提供）：如 `--bundle`、`--checkpoint`、`--host`、`--port` 等。

### 3.7 `runtime`

```json
"runtime": {
  "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
  "sm120-cu130-linux-x86_64-py312": "runtime/sm120-cu130-linux-x86_64-py312"
}
```

- **键（env key）**：目标运行环境标识，格式见 §5.1。
- **值**：相对 bundle 根的目录路径，**必须** 以 `runtime/` 开头，且目录名与 key 一致为佳。
- manifest 中列出的每个 key，发布包内 **必须** 存在对应目录及完整 `.so` 集合。

### 3.8 完整示例（单 preset，节选）

```json
{
  "format": "flashcli-model-bundle",
  "format_version": 3,
  "protocol_version": 1,
  "name": "pi05_libero",
  "description": "Pi0.5 LIBERO VLA",
  "python_abi": "312",
  "entry": {
    "run": { "module": "run", "attr": "RunEngine" }
  },
  "python_dependencies": {
    "torch": { "package": "torch", "index": "auto" },
    "pip": ["numpy", "pyyaml", "safetensors", "transformers<4.56", "pillow"]
  },
  "run_options": [
    {
      "name": "prompt",
      "type": "string",
      "default": "pick up the block",
      "help": "Task instruction.",
      "phase": "predict"
    },
    {
      "name": "num_views",
      "type": "integer",
      "default": 2,
      "help": "Number of camera views.",
      "phase": "load"
    }
  ],
  "weights": {
    "source": "huggingface",
    "repo": "lerobot/pi05_libero_finetuned_v044",
    "revision": "main"
  },
  "runtime": {
    "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
    "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312"
  }
}
```

variants 完整示例见仓库 `bundles/qwen_nvfp4/flashcli-bundle.json`。

---

## 4. entry 入口定义规则

### 4.1 模块位置与 import

- `entry.*.module` 对应 bundle 根下的 `{module}.py`（或包目录）。
- bundle 根在运行时加入 `PYTHONPATH`；entry 及同目录 helper 可直接 `import`。
- entry **只能** 依赖 **`flashcli_bundle`** 协议包（manifest、options、protocol 类型），**不得** `import flashcli` CLI 包。

推荐 import：

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults, serve_option_defaults
from flashcli_bundle.protocol import ChatRequest, ChatResult, RunEngine, ServeEngine
from flashcli_bundle.preset import Preset
```

### 4.2 `RunEngine` 协议

类名与 manifest `entry.run.attr` 一致（通常为 `RunEngine`），须实现：

| 方法 | 说明 |
|------|------|
| `load(checkpoint: Path, preset: Preset, **options)` | 加载权重；`**options` 含 manifest 中 `phase: "load"` 的 run_options |
| `predict(*, prompt: str = "", images: list \| None = None, **kwargs)` | 推理；`**kwargs` 含 `phase: "predict"` 的 run_options |

默认值须通过 `run_option_defaults(bundle, variant=…)` / `option_value()` 读取，**勿**在代码中重复 manifest 已有 default。

### 4.3 `ServeEngine` 协议

类名与 manifest `entry.serve.attr` 一致（通常为 `ServeEngine`），须实现：

| 方法 / 属性 | 说明 |
|-------------|------|
| `model_id`（property） | OpenAI API 暴露的 model id |
| `load(checkpoint, preset, **options)` | `serve_options` 中 `phase: "load"` 的参数 |
| `warmup(spec)` | `serve_options` 中 `phase: "warmup"` 相关；CUDA graph 预热等 |
| `chat(request: ChatRequest) -> ChatResult` | 非流式 |
| `chat_stream(request) -> Iterator[ChatChunk]` | 流式 |

### 4.4 文件对应关系

| manifest | 发布包内文件 |
|----------|----------------|
| `"entry": { "run": { "module": "run", … } }` | 根目录 `run.py`，内含 `RunEngine` 类 |
| `"entry": { "serve": { "module": "serve", … } }` | 根目录 `serve.py`，内含 `ServeEngine` 类 |
| 两者兼有 | `run.py` 与 `serve.py` **均** 必须存在 |

---

## 5. Native `.so` 目录与命名

### 5.1 环境键（env key）

格式：

```text
sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}
```

| 段 | 含义 | 示例 |
|----|------|------|
| `SM` | NVIDIA compute capability × 10，无小数点 | `89` → SM8.9；`120` → SM12.0 |
| `CUDA` | CUDA **用户态**版本缩写 | `124` → 12.4；`130` → 13.0 |
| `os` | 操作系统 | 当前为 `linux` |
| `arch` | CPU 架构 | 当前为 `x86_64` |
| `PY` | Python ABI，与 `python_abi` 一致 | `312` → 3.12 |

示例：`sm89-cu124-linux-x86_64-py312`、`sm120-cu130-linux-x86_64-py312`。

### 5.2 目录放置原则

1. **发布态** 所有 native `.so` 位于 `runtime/<env-key>/`，与 manifest `runtime` 映射一致。
2. 每个 env key 目录内放置 **该环境完整** 的模块集合（见 §5.3）。
3. **禁止** 在 bundle 根目录或 `lib/` 下附带 `.so`（`lib/` 仅本地编译中间态）。
4. `flash_rt/` 目录只含 **Python 源码**，不含 `.so`。
5. 终端 sync 时 **仅下载** 与本机 env key 匹配的那一个 `runtime/<env-key>/` 目录（外加 manifest 与 entry 源码树）。

### 5.3 文件名规则

单个 `.so` 文件名：

```text
{module_base}-{flashrt_abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

| 部分 | 说明 |
|------|------|
| `module_base` | 逻辑模块名，见下表 |
| `flashrt_abi` | FlashRT 构建标识（release tag 或 git commit 前缀，仅 `[a-zA-Z0-9._-]`） |
| 后缀 env 段 | 必须与所在目录 env key 的 `sm/cu/os/arch/py` 一致 |

支持的 `module_base`（按前缀匹配，长名优先）：

| module_base | 必要性 |
|-------------|--------|
| `flash_rt_kernels` | **必填** |
| `flash_rt_fa2` | **必填**（FlashRT attention） |
| `flash_rt_fp4` | 按需（NVFP4 等 FP4 路径） |
| `libfmha_fp16_strided` | 按需（部分 bundle 额外 FMHA） |

示例：

```text
flash_rt_kernels-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fp4-v1.2.0-sm120-cu130-linux-x86_64-py312.so
```

加载时 pybind 导入名仍为 `flash_rt_kernels` / `flash_rt_fa2` 等（**不含** env 后缀）。

### 5.4 矩阵发布建议

- 每个支持的 `(SM, CUDA, python_abi)` 组合对应 **一个** env key 目录。
- 同一 bundle 内各 env key 目录中的 `module_base` 集合应一致（例如都含 kernels + fa2，或再加 fp4）。
- `python_abi` 在 manifest 中为 **单一** 值；各 env key 的 `-py{PY}` 后缀须与之相同。

---

## 6. 发布前自检清单

- [ ] `format_version: 3`、`protocol_version: 1`
- [ ] `flashcli-bundle.json` 位于发布根目录
- [ ] `entry` 指向的 `{module}.py` 均存在且类名匹配
- [ ] `runtime` 每个 key 在包内均有目录，且含 `flash_rt_kernels*.so` 与 `flash_rt_fa2*.so`
- [ ] 无 stray `.so` 在 bundle 根或 `lib/`
- [ ] 存在 `flash_rt/` Python 树
- [ ] 有 `variants` 时无顶层 `run_options`/`serve_options`/`weights`；各 variant 配置完整
- [ ] FlashHub 上传后 `bundle.repo` URL 可返回完整 `files[]` 列表（含子目录下 `.so` 的 `download_url`）

---

## 7. 相关文档

| 文档 | 内容 |
|------|------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | 英文版 |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | 与本文互补的运行时流程摘要 |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
| [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) | 内部：编译、打包、CI、flashcli 命令 |
