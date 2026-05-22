# flashcli 模型包标准（Model Bundle）

<p align="right"><a href="model_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

第三方通过 **Model Bundle** 交付：一份 **`flashcli-bundle.json`**、**`entry` 推理模块**、可选 **FlashRT `.so` / `flash_rt` Python**。flashcli **仅**加载 bundle 并调用 `entry`，**不**在 flashcli 源码中实现具体 Run/Serve 逻辑。

维护 flashcli 请参阅 [DEVELOPER.zh-CN.md](../codeplan/DEVELOPER.zh-CN.md)。**当前对外 catalog 仅 [`pi05_libero`](../models/models.yaml)**；其他 `bundles/` 草稿在验证前不得写入 `models.yaml`。

Bundle 源在 **`models.yaml`** 中登记：单环境用顶层 **`bundle.zip` / `path` / `git`**；多环境用 **`bundle.variants.<sm*-cu*-os-arch>`** 各配独立源。Git 仓或 zip 包内也可含 **`variants/<sm-cu-os-arch>/`**（单源多环境，解压/clone 后按 GPU 选子目录）。

## 目录布局（`format_version` ≥ 2）

`{bundle_root}` 即运行时根（git variant、`--bundle`、或 `~/.flashcli/bundles/...` 缓存）。**无硬性子目录**；只需 `flashcli-bundle.json` 与 `entry` 指向的 Python 模块。

```text
{bundle_root}/
├── flashcli-bundle.json    # 必须：entry、weights、python_dependencies、modules
├── run.py                  # 示例：entry.run.module = "run"
├── *.so                    # 可选：路径写在 modules[].file（位置自定）
├── flash_rt/               # 可选：FlashRT Python（官方包推荐；不含重复 .so）
└── checkpoint/             # 可选：内嵌权重
```

**官方参考包（`pi05_libero`）** 发布 zip 仅含：`flashcli-bundle.json`、`run.py`、`_pi05_compat.py`、`flash_rt_kernels.so`、`flash_rt_fa2.so`、裁剪版 `flash_rt/`（无包内 `.so`）。

**第三方**：可仅 `run.py` + `modules` 中的 `.so`（`import flash_rt_kernels`），或自带 `flash_rt/` 树；`.so` **只发布一份**，路径在 `modules[].file` 声明即可。

激活时 flashcli 将 **`bundle_root`** 加入 `PYTHONPATH`，按 `modules` 预加载 pybind 扩展（并注册 `flash_rt.<name>` 别名，便于 `import flash_rt.flash_rt_kernels`）。

### 旧版布局（`format_version` 1，仍兼容）

`runtime/manifest.json` + `runtime/python/partner/` + `runtime/lib/*.so` 仍可使用；新包请使用 v2。

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
  "python_dependencies": {
    "torch": "torch",
    "pip": ["numpy", "transformers<4.56", "safetensors"],
    "optional_groups": { "server": ["fastapi", "uvicorn"] }
  },
  "cuda": {
    "cuda_tag": "124",
    "recommended_torch_index": "cu124"
  },
  "modules": [
    { "file": "flash_rt_kernels.so", "optional": false, "sha256": "..." }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `format_version` | `2`：扁平 bundle 根；`1`：旧 `runtime/` 树 |
| `capabilities` | `run`、`serve` |
| `entry.run` / `entry.serve` | 相对 **bundle 根** PYTHONPATH 的模块 + 类名 |
| `python_dependencies` | pip / torch（原 `manifest.json` 内容） |
| `cuda` | `cuda_tag`、`recommended_torch_index` 等 |
| `modules` | 可选 `.so` 列表；`file` 为相对 bundle 根路径；`optional` / `sha256` |
| `weights` / `extra_weights` | 主/附加权重下载 |
| `defaults` / `serve` | 传给引擎的默认参数 |
| `post_pull` | 拉权重后步骤（tokenizer 等） |
| `requires.sm` | 可选：variant 选择提示 |
| `build` / `native_libs` | 构建脚本写入的快照元数据 |

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
  "python_dependencies": { "torch": "torch", "pip": ["numpy", "pillow", "..."] },
  "modules": [{ "file": "flash_rt_kernels.so", "optional": false }]
}
```

catalog 通过 `models.yaml` 的 `bundle.variants`（或顶层 `bundle.zip`）指向已组装的 bundle；权重由 HF 拉取。维护者从源码构建见 [bundles/pi05_libero/README.zh-CN.md](../bundles/pi05_libero/README.zh-CN.md)。用户可用 `flashcli models envs <preset>` 查看本机是否匹配已配置环境。

### 示例：LLM + `serve`（内部草稿，未发布）

Qwen NVFP4 等包使用 `capabilities: ["run", "serve"]` 与 `requires.sm: ["120"]`，需 `scripts/build_qwen_bundle.sh` 在 SM120 上构建。**验证通过前不要写入 catalog。**

## `entry` 入口约定

- `entry.*.module` 相对于 **bundle 根**（如 `run` → `run.py`）。
- 类实现 flashcli [`engines/base.py`](../src/flashcli/engines/base.py) 中的 `RunEngine` / `ServeEngine` 协议。
- 可 `from flashcli.bundle.activate import active_bundle` 读取 `defaults` / `serve`。
- 推理逻辑（`flash_rt`、`transformers`、仅 `.so` 算子等）**全部在 entry 模块内**。

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

**仅** preset 名与 bundle 源。支持两种写法：

### 单 bundle（兼容）

顶层 `zip` / `path` / `git` 适用于所有环境。若 zip/git 包内带有 `variants/<sm-cu-os-arch>/`，解压或 clone 后仍按 GPU 自动选子目录。

```yaml
models:
  pi05_libero:
    bundle:
      zip: https://cdn.example/.../multi-variant-bundle.zip
      # path: bundles/pi05_libero
      # git: { repo: "...", ref: main }
```

### 多环境 catalog（`bundle.variants`）

为每台机器声明源；环境键名与 git 仓一致：`sm{SM}-cu{CUDA_TAG}-{os}-{arch}`。当前 GPU 无对应项时会报错并列出已配置环境。可用 `flashcli models envs [preset]` 查看本机匹配项。

**多环境共用同一 zip**（例如 SM89 包在 SM120 上可跑）：各环境键都要存在，可写相同 `zip`，或用**别名**指向另一环境键，或用 YAML anchor（`&id` / `*id`）。

```yaml
models:
  pi05_libero:
    bundle:
      variants:
        sm89-cu130-linux-x86_64:
          zip: https://cdn.example/.../sm89.zip
        sm120-cu128-linux-x86_64: sm89-cu130-linux-x86_64   # 别名，共用上一项的 zip
      refs: { "main": { default: true } }  # 可选，对各 variant 的 git 生效
```

若**所有** GPU 共用一包、无需按环境区分 catalog，可省略 `variants`，仅用顶层 `zip:` / `path:` / `git:`。

| 字段 | 说明 |
|------|------|
| `bundle.path` | 相对 flashcli 包根目录的本地包（可为含 `variants/` 的目录树） |
| `bundle.git` | 远程仓 + 默认 ref |
| `bundle.zip` | 远程 URL 或本地 `.zip` |
| `bundle.variants` | 按环境键覆盖 `zip` / `path` / `git` |
| `bundle.refs` | 可选 git ref 白名单 |

Bundle 解析：`--bundle` > **catalog 按 GPU 选源** > 缓存 > zip 下载/解压 或 git clone >（单 zip/git 时）包内 `variants/` 子目录。

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

内部草稿 Qwen 包使用 `scripts/build_qwen_bundle.sh`（**SM120**）；验证通过前勿加入 catalog。见 [bundles/README.zh-CN.md](../bundles/README.zh-CN.md)。

## 最小交付清单

1. `flashcli-bundle.json`（`format_version` ≥ 2：`entry`、`python_dependencies`、可选 `modules` / `cuda`）
2. `entry` 指向的 Python 模块（如 `run.py` + `RunEngine`）
3. 可选：`modules[].file` 所列 `.so`（各文件只发布一份）
4. 可选：`flash_rt/` Python 树（官方 FlashRT 包）
5. 权重：`checkpoint/` 或 `weights.repo`

## 验证

```bash
flashcli bundle validate /path/to/bundle
flashcli run pi05_libero --bundle /path/to/bundle --image /path/to/base.jpg
# serve 类 bundle 在验证通过后：
# flashcli bundle install /path/to/bundle --profile serve
# flashcli serve <preset> --bundle /path/to/bundle --port 8000
```
