# flashcli 运行包方案（会议讨论稿）

<p align="right"><a href="runtime-package-schemes.md">English</a></p>

**问题：** 现状一个 zip 含全部环境 `lib/*.so`，用户只需一种 GPU 环境却下载整包。  
**边界：** flashcli 只加载 bundle、装依赖、拉权重、调 `entry`；不实现模型推理逻辑。

**环境键（三方案通用）：** `sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`  
例：`sm120-cu130-linux-x86-py312`

---

## 现状

| | |
|--|--|
| **核心** | 模型方把「py + 该模型支持的多环境 so」打成一个 zip；推理端一次下完整包，运行时从 `lib/` 选匹配 so。 |
| **Bundle** | `flashcli-bundle.json`、`run.py`/`serve.py`、`flash_rt/`、**`lib/` 多环境 `*.so`**；权重可选 `checkpoint/` 或 HF。 |
| **flashcli** | 下 zip → 解压 → 装 `python_dependencies` → 按本机环境键从 `lib/` 加载 so → 拉权重 → 调 `entry`。 |
| **模型方** | 为本模型声明的支持环境分别编译 FlashRT so，merge 进 `lib/`，`release_bundle.sh` 打**一个** zip 上传。 |
| **推理端加载 so** | 整包已在 `~/.flashcli/bundles/<preset>/`；`activate` 时扫描 `lib/`，选文件名匹配本机环境键的 `*.so` 加载。 |

```text
{bundle_root}/
├── flashcli-bundle.json
├── run.py, serve.py, flash_rt/
└── lib/                    # 含该模型支持的全部环境 so
    └── flash_rt_*-sm120-cu130-...-py312.so
    └── flash_rt_*-sm89-cu124-...-py310.so
```

| 优点 | 缺点 |
|------|------|
| 已落地，一条脚本出包 | 首包体积大（含全部 so） |
| flashcli 不维护 FlashRT 制品 | 模型方承担多环境编译 |

---

## 改进方案 A：分包下载（so 仍由模型方编译）

| | |
|--|--|
| **核心** | 发布逻辑不变：模型方仍为**该模型支持的环境**编译 so；**分发**拆成「外围包（无 so）」+「按环境 so 包」，推理端只下匹配环境。 |
| **Bundle（逻辑完整形态）** | 与现状相同：`flashcli-bundle.json`、`entry`、`flash_rt/`、**`lib/` 下各环境 so**（构建时仍 merge 到 `lib/` 目录规范）。 |
| **Bundle（推理端实际下载）** | ① **base zip**：json + py + `flash_rt/`，**不含** `lib/*.so`；② **native zip（按环境）**：仅该模型 `lib/` 中某一环境键对应的 `*.so`。 |
| **flashcli** | 下 base zip → 检测本机环境键 → 下对应 native zip → 解压/合并到本地 `bundle_root/lib/` → 其余同现状（依赖、权重、`entry`）。需在 catalog/manifest 声明 base 与 native 的 URL 规则。 |
| **模型方** | 与现状相同：多环境编译 so 到 `lib/`；**发布**时拆成 `bundle-base.zip` + `bundle-native-<env-key>.zip`（或 CDN 目录等价物）。 |
| **推理端加载 so** | base 解压到 `~/.flashcli/bundles/<preset>/` → 拉取 `native-<env-key>.zip` 解压进 `lib/` → `activate` 从 `lib/` 选型加载（与现状一致）。 |

```text
# 模型方构建（与现状一致）
lib/
  flash_rt_*-sm120-cu130-...-py312.so
  flash_rt_*-sm89-cu124-...-py310.so

# 推理端缓存（下载后合并）
~/.flashcli/bundles/<preset>/
├── flashcli-bundle.json, run.py, flash_rt/   ← base zip
└── lib/
    └── flash_rt_*-sm120-cu130-...-py312.so   ← 仅本机环境 native zip
```

| 优点 | 缺点 |
|------|------|
| 推理端首包小，只下本环境 so | 模型方仍要多环境编译 so |
| 对 flashcli 改动相对小（下载层拆分） | 发布物变多，需约定 base/native URL 与 manifest 字段 |
| 不改变 so 归属（仍在模型制品侧） | 每个模型各维护一套 native 包 |

---

## 改进方案 B：flashcli 统一提供 FlashRT 运行时 so

| | |
|--|--|
| **核心** | **so 由 flashcli 按「FlashRT Release 版本 × 环境键」统一编译、发布**；模型 bundle **不含** so；模型方只用 flashcli **已支持**的 FlashRT Release 版本做开发与打包。 |
| **Bundle** | `flashcli-bundle.json`（含 **`flashrt_version`**，须为 flashcli 支持列表内）、`run.py`/`serve.py`、`flash_rt/`；**无 `lib/*.so`**；权重同现状。 |
| **flashcli** | 维护各 Release 的 so 矩阵并发布；公布**支持的 FlashRT Release 列表**及环境键；推理时读 bundle 的 `flashrt_version` + 本机环境键 → 下载 flashcli 提供的 so → 缓存到 `~/.flashcli/runtimes/<version>/<env-key>/` → 注入加载 → 依赖、权重、`entry` 同现状。 |
| **模型方** | 选用 flashcli 文档中的 **FlashRT Release** 本地联调；`flashcli-bundle.json` 写入 `flashrt_version`；打包 **仅 py + manifest**（不编译、不上传 so）。 |
| **推理端加载 so** | 下瘦 bundle → 读 `flashrt_version` → 检测环境键 → 从 flashcli CDN/HF 拉 `runtimes/<version>/<env-key>/*.so` → 加载（可 symlink/拷贝到 bundle `lib/` 或直载）→ `activate` + `entry`。 |

```text
# 模型 zip（模型方发布）
{bundle_root}/
├── flashcli-bundle.json    # flashrt_version: "x.y.z"
├── run.py, serve.py, flash_rt/

# flashcli 发布（与模型无关，多模型共用）
runtimes/<flashrt_version>/<env-key>/
├── flash_rt_kernels-...-py312.so
└── flash_rt_fa2-...-py312.so

# 推理端缓存
~/.flashcli/bundles/<preset>/          ← 瘦 bundle
~/.flashcli/runtimes/x.y.z/sm120-cu130-linux-x86-py312/  ← so
```

| 优点 | 缺点 |
|------|------|
| 模型方免编译 so，bundle 最小 | flashcli 承担全量 Release×环境矩阵编译与维护 |
| 多模型共用同一套运行时 so | 新 FlashRT Release 须 flashcli 先发布才能用 |
| FlashRT 版本可对齐、便于协作 | 依赖 FlashRT 规范 Release tag；需锁定首批环境 |

---

## 三方案对比（会议用）

| | 现状 | 改进 A：分包下载 | 改进 B：flashcli 托管 so |
|--|------|------------------|-------------------------|
| **so 谁编译** | 模型方 | 模型方 | **flashcli** |
| **模型 bundle 含 so** | 是（全环境在一个 zip） | 构建含；**下载不含**（按环境补） | **否** |
| **推理端下载** | 一个完整 zip | base zip + 本环境 native zip | 瘦 bundle + flashcli runtime so |
| **flashcli 新增职责** | — | 分包 URL 解析、合并 `lib/` | Release 矩阵编译、发布、版本清单、runtime 下载 |
| **模型方发布** | 多环境编译 + 单 zip | 多环境编译 + base/native 分包 | 仅 py；`flashrt_version` 须在支持列表内 |
| **so 加载点** | 本地 `bundle/lib/` | 合并后的 `bundle/lib/` | `~/.flashcli/runtimes/<ver>/<env-key>/` |

---

## 会议待决

1. 短期是否继续现状，或先上 **改进 A**（改动小、立刻减下载量）？  
2. **改进 B** 的首个 FlashRT Release / ref 与环境矩阵范围（如 sm120-cu130 + py310–312）？  
3. FlashRT 是否建立正式 **Release tag**（改进 B 前置条件）？  
4. `flashcli-bundle.json` 是否新增字段：`native_layout: split`（A）、`flashrt_version`（B）？

---

## 参考

- [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md) — 现状 bundle 规范  
- [runtime-matrix.zh-CN.md](runtime-matrix.zh-CN.md) — `lib/` 命名与环境键
