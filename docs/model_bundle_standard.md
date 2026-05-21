# flashcli 模型包标准（Model Bundle）

第三方通过 **Model Bundle** 交付：自带 **runtime**、**partner 推理入口**、权重说明。flashcli **仅**加载 bundle 并调用 `entry`，**不**在 flashcli 源码中实现具体 Run/Serve 逻辑。

维护 flashcli 请参阅 [DEVELOPER.md](DEVELOPER.md)。**当前对外 catalog 仅 [`pi05_libero`](../models/models.yaml)**；其他 `bundles/` 草稿在验证前不得写入 `models.yaml`。

Bundle 源可以是 **`bundle.zip`（CDN）**、本地 `bundle.path`、或 Git `variants/<sm-cu-os-arch>/`（一模型一仓可选）。

## 目录布局

`{bundle_root}` 为包根（git variant 目录、`--bundle`、或 `~/.flashcli/bundles/...` 缓存）：

```text
{bundle_root}/
├── flashcli-bundle.json       # 必须：清单、weights、entry
├── partner/                   # 推荐：入口源码（build 复制到 runtime/python/partner/）
│   ├── run.py                 # RunEngine
│   └── serve_*.py             # ServeEngine
├── checkpoint/                # 可选：内嵌权重
└── runtime/
    ├── manifest.json          # Python 依赖、CUDA 元数据
    ├── lib/                   # native_runtime 时：*.so
    └── python/                # 加入 PYTHONPATH
        ├── partner/           # entry 模块（import partner.run 等）
        └── flash_rt/          # 可选：FlashRT 树 + 链接的 .so
```

### 两种 runtime 类型

| 类型 | `native_runtime` | 内容 |
|------|------------------|------|
| **FlashRT 包** | `true`（默认） | `lib/*.so` + `python/flash_rt` + `partner/` |
| **Python-only 包** | `false` | 仅 `manifest.json` + `python/partner/`（扩展用；仓库示例 bundle 均为 FlashRT 包） |

激活时 flashcli 将 `runtime/python` 加入 `PYTHONPATH`；若仅有 `bundle_root/partner/`，会自动链接或复制到 `runtime/python/partner/`。

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
  "format_version": 1,
  "name": "my-model",
  "description": "可选说明",
  "native_runtime": true,
  "runtime_dir": "runtime",
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
    "run": {
      "module": "partner.run",
      "attr": "RunEngine"
    },
    "serve": {
      "module": "partner.serve",
      "attr": "ServeEngine"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `native_runtime` | `false` 时不要求 `lib/flash_rt_kernels.so` |
| `runtime_dir` | 默认 `runtime` |
| `capabilities` | `run`、`serve` |
| `entry.run` / `entry.serve` | **`partner` 包内**模块名 + 类名 |
| `weights` / `extra_weights` | 主/附加权重下载 |
| `defaults` / `serve` | 传给引擎的默认参数（由 partner 读取） |
| `post_pull` | 拉权重后步骤（tokenizer 等） |
| `requires.sm` | 可选：variant 选择提示 |
| `git_ref` / `native_libs` | 构建脚本写入（发布快照元数据） |

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
  "entry": {
    "run": {
      "module": "partner.run",
      "attr": "RunEngine"
    }
  }
}
```

catalog 通过 `models.yaml` 的 `bundle.zip` 指向已组装的 runtime；权重由 HF 拉取。维护者从源码构建见 [bundles/pi05_libero/README.md](../bundles/pi05_libero/README.md)。

### 示例：LLM + `serve`（内部草稿，未发布）

Qwen NVFP4 等包使用 `capabilities: ["run", "serve"]` 与 `requires.sm: ["120"]`，需 `scripts/build_qwen_bundle.sh` 在 SM120 上构建。**验证通过前不要写入 catalog。**

## `partner/` 入口约定

- 模块路径相对于 `runtime/python`（如 `partner.run` → `runtime/python/partner/run.py`）。
- 类实现 flashcli [`engines/base.py`](../src/flashcli/engines/base.py) 中的 `RunEngine` / `ServeEngine` 协议。
- 可 `from flashcli.bundle.activate import active_bundle` 读取 `flashcli-bundle.json` 中的 `defaults` / `serve`。
- 调用 bundle 内 `flash_rt`（NVFP4/VLA 等）或 transformers 等，**逻辑全部写在 partner 内**。

开发阶段可将 `partner/` 放在 `bundle_root/partner/`；`build_*_bundle.sh` 会 `rsync` 到 `runtime/python/partner/`。

## `runtime/manifest.json`

由 `scripts/generate_runtime_manifest.py` 在构建时生成，或手写（Python-only 包），例如：

```json
{
  "format": "flashrt-runtime-manifest",
  "format_version": 1,
  "python_dependencies": {
    "torch": "torch",
    "pip": ["numpy", "transformers<4.56", "safetensors"],
    "optional_groups": { "server": ["fastapi", "uvicorn"] }
  },
  "cuda": {
    "cuda_tag": "124",
    "recommended_torch_index": "cu124"
  }
}
```

`native_runtime: true` 时，`lib/*.so` 在激活时链接到 `runtime/python/flash_rt/`。

## flashcli 推理协议（宿主侧）

bundle 内 `partner` 实现以下接口；flashcli `serve` 提供固定 HTTP 路由。

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

## Git 多环境仓库

```text
flashcli-bundle-my-model/
├── variants/
│   ├── sm89-cu124-linux-x86_64/
│   │   ├── flashcli-bundle.json
│   │   └── runtime/
│   └── sm120-cu128-linux-x86_64/
└── README.md
```

目录名：`sm{SM}-cu{CUDA_TAG}-{os}-{arch}`。

**版本 = git ref**（branch / tag），不用 `variants/env/1.0.0/` 子目录。

ref 优先级：`--bundle-ref` > `bundle.git.ref` > `refs[].default` > `main`。

### 本地缓存

```text
~/.flashcli/bundles/<preset>/refs/<sanitized_ref>/
~/.flashcli/bundles/<preset>/.flashcli_bundle.json
```

权重独立：`~/.flashcli/models/<preset>/checkpoint/`。

## `models/models.yaml`

**仅** preset 名与 bundle 源：

```yaml
schema_version: 4

models:
  pi05_libero:
    description: Pi0.5 LIBERO (SM89/SM120)
    bundle:
      zip: https://cdn.example/.../1.0.0-sm89-cu130-linux-x86_64.zip
      # 维护者本地：path: bundles/pi05_libero
```

| 字段 | 说明 |
|------|------|
| `bundle.path` | 相对 flashcli 包根目录的本地包 |
| `bundle.git` | 远程仓 + 默认 ref |
| `bundle.zip` | 远程 URL 或本地 `.zip`（解压后缓存于 `~/.flashcli/bundles/<preset>/zip/`） |
| `bundle.refs` | 可选 ref 白名单 |

Bundle 解析：`--bundle` > `bundle.path` > 缓存 > **zip 下载/解压** 或 **git clone**（按 GPU 选 variant）。

## 构建脚本（FlashRT 源码树，Linux GPU）

```bash
# Pi0.5：需编译 flash_rt_kernels + 打入 partner/
bash flashcli/scripts/build_pi05_bundle.sh \
  --bundle-dir flashcli/bundles/pi05_libero

# 仅重打包（已有 .so）
bash flashcli/scripts/build_pi05_bundle.sh --bundle-dir ... --pack-only

# 内嵌权重
bash flashcli/scripts/build_pi05_bundle.sh \
  --embed-checkpoint ~/.flashcli/models/pi05_libero/checkpoint
```

内部草稿 Qwen 包使用 `scripts/build_qwen_bundle.sh`（**SM120**）；验证通过前勿加入 catalog。见 [bundles/README.md](../bundles/README.md)。

## 最小交付清单

1. `flashcli-bundle.json`（含 `entry` → `partner.*`）
2. `runtime/manifest.json`
3. `runtime/python/partner/`（`RunEngine` / `ServeEngine`）
4. 若 `native_runtime`：`runtime/lib/*.so` + `runtime/python/flash_rt/`
5. 权重：`checkpoint/` 或 `weights.repo`

## 验证

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
# serve 类 bundle 在验证通过后：
# flashcli bundle install /path/to/bundle --profile serve
# flashcli serve <preset> --bundle /path/to/bundle --port 8000
```
