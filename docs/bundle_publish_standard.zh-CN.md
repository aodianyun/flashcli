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

终端用户通过 inline ref（`flashcli-bundle/<name>:<version>[@variant]`）获取 bundle；flashcli 先下载 `flashcli-bundle.json`，再按本机 GPU/CUDA/Python 匹配 `runtime` 中的 env key，仅下载对应 `runtime/<env-key>/` 下的文件。

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

同一 repo 内 **`entry` 相同**，ref 中的 `@variant` 选择 variant 块中的权重与 options：

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

### 2.4 Preset ref（供集成方参考）

用户使用 inline ref 字符串 — 在 [FlashHub](https://flashhub.top) 发现 bundle；flashcli 仓库内无 bundled catalog 文件：

```text
flashcli-bundle/<name>:<version>[@variant]
```

示例：

```bash
flashcli run flashcli-bundle/pi05_libero:1.0.4
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen3
flashcli run flashcli-bundle/qwen_nvfp4:1.0.1@qwen36
```

- **单 variant bundle** — ref 仅为 `namespace/bundle:version`。
- **多 variant bundle** — ref **必须**带 `@variant`。
- **本地 dev** — `flashcli run bundles/qwen_nvfp4@qwen36`（目录须含 `flashcli-bundle.json`）。

完整语法：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

---

## 3. `flashcli-bundle.json` 配置详解

### 3.0 作者 manifest（禁止 build 覆盖）

源码目录中的 **`flashcli-bundle.json` 为权威、完整，由发布者维护**。所有产品字段（`python_dependencies`、`weights`、`run_options` 等）须在 git 中手写维护；build/pack **不得**覆盖该文件，仅可写 `.build/manifest-overlay.json`（构建元数据），并在 pack 时合并为 **`dist/flashcli-bundle.json`**。详见 [bundle_manifest_policy.md](bundle_manifest_policy.md)。

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
| `post_pull` | 否 | 主机侧权重拉取后钩子（非 Hub 资源，如 PaliGemma URL）。Hugging Face / ModelScope 侧车资源优先用 `extra_weights` |

### 3.2 `entry`

```json
"entry": {
  "run":  { "module": "run",  "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

可选 **`mode`**：`"engine"`（默认）或 `"script"`。engine 模式走 `RunEngine`/`ServeEngine` 协议与 flashcli 内置 HTTP 栈；script 模式将 `run|serve` 的 argv（去掉 REF 后）原样传给 `attr` 指向的可调用对象（通常为 `main`），`run_options`/`serve_options` 仅用于 `flashcli run|serve <ref> --help` 文档。

script 示例：

```json
"entry": {
  "run":  { "module": "run",  "attr": "main", "mode": "script" },
  "serve": { "module": "serve", "attr": "main", "mode": "script" }
}
```

| 子字段 | 说明 |
|--------|------|
| `module` | 相对 bundle 根的 Python 模块名（不含 `.py`），如 `"run"` → `run.py` |
| `attr` | engine 模式：类名（`RunEngine`/`ServeEngine`）；script 模式：可调用入口（如 `main`） |
| `mode` | 可选，`engine`（默认）或 `script` |

能力由 `entry` 推断：有 `run` 即支持 `flashcli run`；有 `serve` 即支持 `flashcli serve`。

entry 执行前由 flashcli 注入、供 bundle 代码读取的环境变量见 **§4.4**（engine 与 script 不同）。

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
| `extra_weights` | 附加权重（如 Qwen MTP、GROOT tokenizer）；见 §3.5.1 |
| `env` | **Engine 模式**：entry 执行前写入进程环境，支持 `{models_dir}`、`{bundle_root}`（见 §4.4.2）。Script 模式不应用 manifest `env`（见 §4.4.1）。 |
| `run_options` / `serve_options` | 该 variant 专属 CLI 参数（结构见 §3.5） |

### 3.4 `python_dependencies`

```json
"python_dependencies": {
  "torch": { "package": "torch", "index": "auto" },
  "pip": [
    "numpy",
    "safetensors",
    "transformers<4.56",
    "torchaudio"
  ]
}
```

| 键 | 说明 |
|----|------|
| `torch` | PyTorch wheel；`index: "auto"` 表示由 flashcli 按本机 CUDA 线选择 cu124/cu128 索引（**推荐**） |
| `pip` | 其余 pip 包列表（字符串，可带版本约束）；**仅安装此处列出的 PyPI 包** |
| `torchaudio` / `torchvision` | 可在 `pip` 中显式列出；若未列出但某个 `pip` 包的 wheel 声明依赖它们，flashcli 会在安装 `torch` 时**一并从 CUDA 索引推断安装**。之后该 PyPI 包会以 `--no-deps` 安装，避免 PyPI 覆盖 CUDA 版本 |

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
| `source` | 当前支持 `"huggingface"`、`"modelscope"` |
| `repo` / `revision` | Hugging Face 模型 id 与分支/提交 |
| `require_norm_stats` | 可选；VLA 等需 norm stats 时为 `true` |

### 3.5.1 `extra_weights`（侧车资源）

用于主 `weights` checkpoint **之外**的 Hugging Face / ModelScope 仓库 — 例如 Qwen3.6 MTP（`cache_name`），或 GROOT 的 Qwen3 tokenizer 与主 checkpoint 同目录存放。

```json
"extra_weights": {
  "qwen3_tokenizer": {
    "source": "huggingface",
    "repo": "Qwen/Qwen3-1.7B",
    "allow_patterns": [
      "tokenizer.json",
      "tokenizer_config.json",
      "vocab.json",
      "merges.txt"
    ],
    "checkpoint_subdir": "tokenizer"
  }
}
```

| 字段 | 说明 |
|------|------|
| `source` / `repo` / `revision` | 同 `weights` |
| `cache_name` | 可选；安装到 `~/.flashcli/models/<cache_name>`（默认用 manifest 键名） |
| `checkpoint_subdir` | 可选；安装到 `{checkpoint}/<subdir>/`，而非独立 cache 目录 |
| `allow_patterns` | 要拉取的文件（Hub CLI `--include`）；Hub 常一次只返回一个文件时，应列出全部必需文件名 |
| `require_any_patterns` | 可选；就绪检查为**任一**匹配（遗留；优先在 `allow_patterns` 中列出全部必需文件） |

**主机 vs infer：** `flashcli pull` 与 `flashcli run` / `serve` 的主机预检会下载 `weights` + `extra_weights` 并执行 `post_pull`。bundle venv 推理阶段设置 `HF_HUB_OFFLINE=1` — 缺文件应重新 `flashcli pull`，而非在运行时访问 Hub。

**Hugging Face 仓库优先用 `extra_weights`，少用 `post_pull`。** `post_pull` 保留给非 Hub 资源（如 Pi0.5 从固定 URL 拉 PaliGemma tokenizer）。

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

**不在 manifest 中声明的参数**（由 flashcli 提供）：如 `--checkpoint`、`--host`、`--port` 等。

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
- bundle 根在运行时加入 `sys.path`；entry 及同目录 helper 可直接 `import`。
- entry **只能** 依赖 **`flashcli_bundle`** 协议包（manifest、options、protocol 类型），**不得** `import flashcli` CLI 包。

#### 4.1.1 Native `.so` 加载（engine / script 相同）

无论 `entry.*.mode` 为 **engine** 还是 **script**，flashcli 在调用 `RunEngine` / `ServeEngine` 或 script `main(argv)` **之前** 都会执行 **activate**：

1. 按本机 GPU / CUDA / `python_abi` 从 manifest `runtime` 选择匹配的 `runtime/<env-key>/`（见 §5）。
2. 将该目录下的 `.so` 注册为 Python 扩展模块（导入名如 `flash_rt_kernels`、`flash_rt_fa2`，**不含**文件名中的 env 后缀；见 §5.3）。
3. 将 bundle 根目录加入 `sys.path`，以便 `import flash_rt` 及同目录 helper。

因此 **script 模式不需要** 也 **不应** 通过环境变量或手动 `dlopen` 加载 `.so`。entry 内与 engine 一样直接 import 即可，例如：

```python
import flash_rt
from flash_rt import flash_rt_kernels
```

`.so` 的发布布局、命名与 env key 规则见 **§5**；与 `§4.4` 中的权重环境变量无关。

本地若直接 `python run.py`（不经过 `flashcli run`），不会自动完成上述 activate；请用 `flashcli run <ref> …` 验证，或仅在开发时自行模拟路径与 native 注册。

推荐 import（engine 协议类型；script 仅需其中与业务相关的部分）：

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

### 4.4 Entry 环境变量（engine / script）

flashcli 在 **权重已校验**、即将调用 entry（`RunEngine` / `ServeEngine` 或 script `main`）之前，向当前进程写入环境变量。第三方 entry **只应依赖本节列出的名称**；其余 `FLASHCLI_*`（如 `FLASHCLI_RUNTIME_ID`、`FLASHCLI_IN_BUNDLE_VENV`）为内部实现，**不保证稳定**。

两种 `entry.*.mode` 注入的变量 **不同**：script 使用平台统一的 `FLASHCLI_*` 绝对路径；engine 使用 manifest 自声明的 `env` 与少量约定名。

#### 4.4.1 Script 模式（`mode: "script"`）

entry 签名为 `def main(argv: list[str] | None = None) -> int | None`（或等价 callable）。用户 CLI 参数在 `argv` 中由 bundle 自行解析；权重路径通过环境变量提供。

| 变量 | 必有 | 说明 |
|------|------|------|
| `FLASHCLI_CHECKPOINT` | 是 | 当前 preset 的 **主权重** 目录（绝对路径，已通过 cache 校验）。 |
| `FLASHCLI_BUNDLE_ROOT` | 是 | 当前 bundle 根目录（绝对路径）。 |
| `FLASHCLI_PRESET` | 是 | 当前 preset ref，与 CLI positional ref 一致（如 `flashcli-bundle/qwen_nvfp4:1.0.1@qwen3`）。 |
| `FLASHCLI_VARIANT` | 否 | ref 含 `@variant` 时写入 variant 名；单 variant bundle 通常 **不** 设置。 |
| `FLASHCLI_EXTRA_WEIGHT_<KEY>` | 否 | 每个 manifest `extra_weights` 条目一条；`<KEY>` 为 manifest 键的大写形式（非字母数字 → `_`）。值为该扩展权重的 **绝对路径**（已校验）。 |

`extra_weights` 键到环境变量名示例：

| manifest `extra_weights` 键 | 环境变量 |
|-----------------------------|----------|
| `vocoder` | `FLASHCLI_EXTRA_WEIGHT_VOCODER` |
| `mtp_fp8` | `FLASHCLI_EXTRA_WEIGHT_MTP_FP8` |

Script 模式 **不会** 应用 manifest 顶层 / variant 的 `env` 块，也 **不会** 注入 `{models_dir}` 占位符展开后的全局 cache 布局。entry 只读上表变量即可。

Native 扩展（`.so`）的加载与 engine 相同，见 **§4.1.1**；script 下同样 `import flash_rt` / `from flash_rt import flash_rt_*`，无需为 `.so` 单独配置环境变量。

示例 `run.py`：

```python
import os
from pathlib import Path

def main(argv: list[str] | None = None) -> int:
    ckpt = Path(os.environ["FLASHCLI_CHECKPOINT"])
    bundle_root = Path(os.environ["FLASHCLI_BUNDLE_ROOT"])
    mtp = os.environ.get("FLASHCLI_EXTRA_WEIGHT_MTP_FP8")  # 若 manifest 声明了 extra_weights.mtp_fp8
    ...
    return 0
```

#### 4.4.2 Engine 模式（默认，省略 `mode` 或 `"engine"`）

主权重 **不** 写入 `FLASHCLI_CHECKPOINT`，而是由 flashcli 调用 `RunEngine.load(checkpoint, preset, **options)` / `ServeEngine.load(...)` 时以 **参数** 传入。扩展路径与模型相关资源通过下列方式进入进程：

| 来源 | 说明 | 示例变量名 |
|------|------|------------|
| manifest **`env`** / variant **`env`** | entry 执行前写入；值可含 `{bundle_root}`、`{models_dir}` 占位符（由 flashcli 展开为绝对路径）。**键名由 bundle 作者定义。** | `FLASHRT_QWEN36_MTP_CKPT_DIR`、`MY_AUX_DIR` |
| **`post_pull`** | 权重拉取后按 manifest 步骤准备附属文件并写入 env。 | `FLASH_RT_PALIGEMMA_TOKENIZER`（Pi0.5 PaliGemma tokenizer 文件路径） |
| CLI **`--mtp-checkpoint`** | 仅 engine 模式由 flashcli 解析；覆盖 manifest `env` 中的 MTP 路径。 | `FLASHRT_QWEN36_MTP_CKPT_DIR` |

manifest `env` 示例（Qwen variant，节选）：

```json
"env": {
  "FLASHRT_QWEN36_MTP_CKPT_DIR": "{models_dir}/qwen_nvfp4/1.0.1@qwen36/mtp_fp8"
}
```

`{models_dir}` 展开为 flashcli 模型缓存根（默认 `~/.flashcli/models`）；`{bundle_root}` 展开为 bundle 根目录。Engine entry 在 `load()` 内通过 `os.environ` 读取作者在 manifest 中声明的键名。

#### 4.4.3 模式对比

| 项目 | Script | Engine |
|------|--------|--------|
| 主权重 | `FLASHCLI_CHECKPOINT` | `load(checkpoint, …)` 参数 |
| 扩展权重 | `FLASHCLI_EXTRA_WEIGHT_<KEY>` | manifest `env` 或自定义键 |
| manifest `env` | **不应用** | **应用** |
| `post_pull` 写入的 env | 若 manifest 含 `post_pull` 仍会执行（准备磁盘文件）；script entry 一般 **不依赖** 其 env，优先用上表 `FLASHCLI_*` | 可读，如 `FLASH_RT_PALIGEMMA_TOKENIZER` |
| `run_options` / `serve_options` | 仅 `--help` 文档；参数在 `argv` 中 | 由 flashcli 解析并传入 engine |
| `--checkpoint` | 留在 `argv`；同时用于 flashcli 校验并写入 `FLASHCLI_CHECKPOINT` | flashcli 解析；传入 `load()`，不写 `FLASHCLI_CHECKPOINT` |
| `--mtp-checkpoint` | **不** 由 flashcli 解析（原样在 `argv`）；扩展权重用 `FLASHCLI_EXTRA_WEIGHT_*` | 写入 `FLASHRT_QWEN36_MTP_CKPT_DIR` |

#### 4.4.4 请勿在 entry 中依赖

| 变量 | 原因 |
|------|------|
| `FLASHCLI_RUNTIME_ID` | re-exec 内部 runtime 矩阵键 |
| `FLASHCLI_IN_BUNDLE_VENV` | 标识 infer 子进程，非业务配置 |
| `FLASHCLI_HOME` / `FLASHCLI_MODELS_DIR` 等 | 主机路径配置；script 应用已解析的 `FLASHCLI_CHECKPOINT` 等，勿自行拼 cache 路径 |
| 其他 bundle 的 cache 路径 | 不会注入；仅当前 preset 的权重 |

运维向完整列表见 [environment.zh-CN.md](environment.zh-CN.md#bundle-entry-环境变量engine--script)。

### 4.5 文件对应关系

| manifest | 发布包内文件 |
|----------|----------------|
| `"entry": { "run": { "module": "run", … } }` | 根目录 `run.py`，内含 `RunEngine` 类 |
| `"entry": { "serve": { "module": "serve", … } }` | 根目录 `serve.py`，内含 `ServeEngine` 类 |
| `"entry": { "run": { "module": "run", "attr": "main", "mode": "script" } }` | 根目录 `run.py`，内含 `main(argv)` |
| 两者兼有 | `run.py` 与 `serve.py` **均** 必须存在 |

---

## 5. Native `.so` 目录与命名

### 5.1 环境键（env key）

格式：

```text
{platform_tail}-{os}-{arch}-py{PY}
```

| 段 | 含义 | 示例 |
|----|------|------|
| `platform_tail` | 不透明平台/运行时标识（仅用于匹配） | `sm120-cu130`（NVIDIA）；`gfx942-rocm611`（AMD ROCm） |
| `os` | 操作系统 | 当前为 `linux` |
| `arch` | CPU 架构 | 当前为 `x86_64` |
| `PY` | Python ABI，与 `python_abi` 一致 | `312` → 3.12 |

NVIDIA bundle 仍使用 `sm{SM}-cu{CUDA}` 作为 `platform_tail`（如 `sm89-cu124-linux-x86_64-py312`）。非 NVIDIA 示例：`gfx942-rocm611-linux-x86_64-py312`。

当前 host 检测仍生成 NVIDIA 风格 key；调试尚无 auto-detect 的 manifest cell 时可设 `FLASHCLI_RUNTIME_ENV_KEY` 强制选中。

### 5.2 目录放置原则

1. **发布态** 所有 native `.so` 位于 `runtime/<env-key>/`，与 manifest `runtime` 映射一致。
2. 每个 env key 目录内放置 **该环境完整** 的模块集合（见 §5.3）。
3. **禁止** 在 bundle 根目录或 `lib/` 下附带 `.so`（`lib/` 仅本地编译中间态）。
4. `flash_rt/` 目录只含 **Python 源码**，不含 `.so`。
5. 终端 sync 时 **仅下载** 与本机 env key 匹配的那一个 `runtime/<env-key>/` 目录（外加 manifest 与 entry 源码树）。

### 5.3 文件名规则

单个 `.so` 文件名：

```text
{module_base}-{flashrt_abi}-{env_key}.so
```

其中 `{env_key}` 即目录名（见 §5.1）。NVIDIA 示例：

```text
{module_base}-{flashrt_abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

| 部分 | 说明 |
|------|------|
| `module_base` | pybind 逻辑导入名（任意合法段，如 `flash_rt_kernels`、`flash_rt_omnivoice`） |
| `flashrt_abi` | FlashRT 构建标识（release tag 或 git commit 前缀，单段 `[a-zA-Z0-9._-]`） |
| `env_key` | 必须与所在 `runtime/<env-key>/` 目录名一致 |

cell 目录内所有符合 `{module_base}-{flashrt_abi}-{env_key}.so` 的文件均会被 discover 并加载（无 manifest 白名单）。同一 `module_base` 若有多条 ABI 构建，host 会 deterministic 选一条（发布侧建议每 module 仅一条）。

示例：

```text
flash_rt_kernels-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_fa2-v1.2.0-sm89-cu124-linux-x86_64-py312.so
flash_rt_omnivoice-1.0.0-sm120-cu130-linux-x86_64-py312.so
flash_rt_fp4-v1.2.0-sm120-cu130-linux-x86_64-py312.so
```

加载时 pybind 导入名仍为 `flash_rt_kernels` / `flash_rt_fa2` 等（**不含** env 后缀）。

### 5.4 矩阵发布建议

- 每个支持的 `(SM, CUDA, python_abi)` 组合对应 **一个** env key 目录。
- 同一 bundle 内各 env key 目录中的 `module_base` 集合 **建议一致**（例如都含 kernels + fa2，或仅 kernels）。
- `python_abi` 在 manifest 中为 **单一** 值；各 env key 的 `-py{PY}` 后缀须与之相同。

---

## 6. 发布前自检清单

- [ ] `format_version: 3`、`protocol_version: 1`
- [ ] `flashcli-bundle.json` 位于发布根目录
- [ ] `entry` 指向的 `{module}.py` 均存在且类名匹配
- [ ] `runtime` 每个 key 在包内均有目录，且含 **至少一个** 可识别的 tagged native `.so`
- [ ] 无 stray `.so` 在 bundle 根或 `lib/`
- [ ] 存在 `flash_rt/` Python 树
- [ ] 有 `variants` 时无顶层 `run_options`/`serve_options`/`weights`；各 variant 配置完整
- [ ] FlashHub 上传后 `bundle.repo` URL 可返回完整 `files[]` 列表（含子目录下 `.so` 的 `download_url`）

---

## 7. 相关文档

| 文档 | 内容 |
|------|------|
| [bundle_publish_standard.md](bundle_publish_standard.md) | 英文版 |
| [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) | preset ref 与终端用户运行时流程 |
| [flashcli-bundle/README.md](../flashcli-bundle/README.md) | `flashcli_bundle` Python API |
