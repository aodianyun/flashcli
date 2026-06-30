# Runtime 发布矩阵

<p align="right"><a href="runtime-matrix.md">English</a> · <strong>简体中文</strong></p>

> **内部维护者文档** — 仅从 [CONTRIBUTING.md](../CONTRIBUTING.md) 索引；不在对外 README / `docs/README` 中列出。

维护者如何构建 **多 CUDA / SM 环境** 的原生制品，并通过 **FlashHub** 发布。

## 矩阵概览

| Bundle | SM | CUDA 线 | Python ABI | Native 模块 |
|--------|-----|---------|------------|-------------|
| `pi05_libero` | **89**、**120** | cu124（SM89）、cu130 | **3.12**（`python_abi: 312`） | `flash_rt_kernels`, `flash_rt_fa2` |
| `qwen_nvfp4` | **120** | **仅 cu130** | **3.12** | `flash_rt_kernels`, `flash_rt_fa2` |

OS / arch：**linux-x86_64**。配置见 `bundles/<name>/release-matrix.env`。

## 发布目录布局（`dist/`）

构建完成后 `pack_bundle.sh` 产出：

```text
dist/
  flashcli-bundle.json    # runtime: { env_key: "runtime/<env-key>" }
  run.py, flash_rt/, ...
  runtime/
    sm89-cu124-linux-x86_64-py312/
      flash_rt_kernels-...-py312.so
      flash_rt_fa2-...-py312.so
    sm89-cu130-linux-x86_64-py312/
      ...
```

运行时 flashcli 直接从缓存 bundle 根下的 `runtime/<env-key>/` 加载匹配 env 的 `.so`（不会拷贝到 `lib/`）。

每个已发布 bundle 由 **FlashHub ref**（`flashcli-bundle/<name>:<version>[@variant]`）固定 — 见 [model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)。

### Native `.so` 命名（构建阶段）

```text
{模块}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

示例：`flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

### FlashHub 发布

1. `bash scripts/release_bundle.sh --bundle <name> --clean`
2. 上传 `dist/` 整棵树到 FlashHub
3. 告知用户固定新 ref（如在文档中更新 `flashcli-bundle/pi05_libero:1.0.4`）

示例 repo URL：

```text
https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.3
```

### FA2（pi05_libero）

**SM89 + SM120**；manifest 含 `sm89-cu124`、`sm89-cu130`、`sm120-cu130` runtime 档。

| CUDA 线 | FA2 / 内核策略 |
|---------|----------------|
| **cu124**（SM89） | `FA2_ARCH_NATIVE_ONLY` → sm_89 AOT |
| **cu130**（SM89） | FA2 多架构；kernels 为 sm_89 |
| **cu130**（SM120） | cu130 矩阵 pass 交叉编译 sm120 单元 |

## 矩阵构建（通用脚本）

| 脚本 | 作用 |
|------|------|
| `scripts/release_bundle.sh` | **推荐**：FlashRT → Docker/`--native` 矩阵 → finalize → pack |
| `scripts/build_release_matrix.sh` | 宿主机矩阵循环 |
| `scripts/pack_bundle.sh` | 写 `runtime/` + 更新 manifest |

**推荐一键发布：**

```bash
cd flashcli
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

**本地单环境开发：**

```bash
cd bundles/pi05_libero
bash build.sh --repo-root "$FLASHRT_REPO"
```

## 运行时选择（终端用户）

| 阶段 | 行为 |
|------|------|
| `flashcli bundle sync` | FlashHub API → manifest → preflight → 下载源码树 + 本 env `runtime/` |
| `flashcli run` | bundle venv 装 torch → 从 `runtime/<env-key>/` 加载 `.so` → 权重 → `entry` |

本机环境键示例：`sm89-cu124-linux-x86_64-py312`、`sm120-cu130-linux-x86_64-py312`（NVIDIA）。env key 固定尾部为 `-{os}-{arch}-py{PY}`，前缀 `platform_tail` 可为 opaque（如 `gfx942-rocm611-linux-x86_64-py312`）。host 自动检测仍生成 NVIDIA 风格 key；调试新平台可设 `FLASHCLI_RUNTIME_ENV_KEY` 强制选中 manifest cell。  
查看匹配：`flashcli models envs flashcli-bundle/pi05_libero:1.0.3`

**不要**用与 manifest `python_abi` 不一致的系统 Python 跑 bundle（会在 venv / preflight 阶段失败）。

## 本地调试（不经过 FlashHub）

```bash
flashcli run bundles/pi05_libero \
  --image /path/to.jpg
```

本地 dev 树需在 manifest 对应的 `runtime/<env-key>/` 下有 `.so`（`build.sh` 先产出到 `lib/`，再 staging 到 `runtime/`；见各 bundle QUICKSTART）。

---

## qwen_nvfp4（SM120 × cu130）

一个 FlashHub repo（`flashcli-bundle/qwen_nvfp4:1.0.1`）；ref 中 `@qwen3` / `@qwen36` 区分权重。

```bash
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

更新 **两个** variant ref（同一 repo URL，不同 `@variant`）。

环境键示例：`sm120-cu130-linux-x86_64-py312`

包格式：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)
