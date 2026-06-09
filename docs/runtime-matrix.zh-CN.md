# Runtime 发布矩阵

<p align="right"><a href="runtime-matrix.md">English</a> · <strong>简体中文</strong></p>

维护者如何构建 **多 CUDA / SM 环境** 的原生制品，并通过 **FlashHub** 发布。终端用户通过 `bundle.repo` + `flashcli bundle sync` 拉取；**只下载本机 env 的 `runtime/<env-key>/`**，不再下载含全部 env 的单体 zip。

## 矩阵概览

| Bundle | SM | CUDA 线 | Python ABI | Native 模块 |
|--------|-----|---------|------------|-------------|
| `pi05_libero` | **89** | cu124、cu130 | **3.12**（`python_abi: 312`） | `flash_rt_kernels`, `flash_rt_fa2` |
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

运行时 flashcli 将匹配 env 的 `.so` 安装到 bundle 根下的 `lib/`。

每个 preset 在 `models.yaml` 中一个 **`bundle.repo`**（`schema_version: 7`），指向 FlashHub 语义化 URL。

### Native `.so` 命名（构建阶段）

```text
{模块}-{FlashRT_ABI}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}.so
```

示例：`flash_rt_kernels-abc1234-sm89-cu124-linux-x86_64-py312.so`

### FlashHub 发布

1. `bash scripts/release_bundle.sh --bundle <name> --clean`
2. 上传 `dist/` 整棵树到 FlashHub
3. 更新 [`models.yaml`](../src/flashcli/catalog/models.yaml) 中 `bundle.repo` 版本 URL

示例：

```text
https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero/1.0.2
```

### FA2（pi05_libero）

**SM89** 主线；manifest 可含 sm120 runtime 档供扩展。

| CUDA 线 | FA2 策略 |
|---------|----------|
| **cu124** | `FA2_ARCH_NATIVE_ONLY` → sm_89 AOT |
| **cu130** | FA2 多架构；kernels 仍为 sm_89 |

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
| `flashcli run` | bundle venv 装 torch → `lib/` 加载 `.so` → 权重 → `entry` |

本机环境键示例：`sm89-cu124-linux-x86_64-py312`  
查看匹配：`flashcli models envs pi05_libero`

**不要**用与 manifest `python_abi` 不一致的系统 Python 跑 bundle（会在 venv / preflight 阶段失败）。

## 本地调试（不经过 FlashHub）

```bash
flashcli run pi05_libero \
  --bundle "$(pwd)/bundles/pi05_libero" \
  --image /path/to.jpg
```

本地 dev 树需含 `lib/` 或对应 `runtime/<env-key>/` 下的 `.so`。

---

## qwen_nvfp4（SM120 × cu130）

一个 FlashHub repo 服务两个 catalog preset（`qwen3-8b-nvfp4`、`qwen36-27b-nvfp4`），通过 `bundle_variant` 区分权重。

```bash
bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

更新 **两个** preset 的 `bundle.repo`（同一 repo URL，不同 `bundle_variant`）。

环境键示例：`sm120-cu130-linux-x86_64-py312`

包格式：[model_bundle_standard.zh-CN.md](model_bundle_standard.zh-CN.md)
