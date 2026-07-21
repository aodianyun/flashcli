# 构建与发布 — pi05_libero_nexus

本 bundle 维护者文档。

## 构建主机前置条件

- Linux x86_64，**Blackwell GPU**（compute capability 12.0 / `sm_120`）
- CUDA Toolkit 13.0（`nvcc` 在 PATH 中）
- cmake ≥ 3.24，gcc ≥ 11
- python3.10（CPython 3.10 —— 必须匹配 `python_abi: "310"`）
- git、rsync（缺失时自动 fallback 到 tar）
- CUTLASS v4.4.2（构建脚本缺失时自动克隆）

## 源码仓库

- **FlashRT**：必须含 `CMakeLists.txt` + `flash_rt/` + `cpp/` + `exec/` + `runtime/`
- **FlashRT-Nexus**：必须含 `CMakeLists.txt` + `core/` + `serve/`

## 构建命令

```sh
cd /app/flashcli

# 本地开发构建（用已克隆的仓库）。32 GB 内存主机上 -j 4 较平衡：
# FA2 模板编译内存密集，更高 -j 容易 OOM。
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    -j 4

# 仅打包（跳过 cmake，stage 已有 .so —— 手动重编后用）
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    --pack-only

# 覆盖默认值
bash bundles/pi05_libero_nexus/build.sh \
    --repo-root /app/FlashRT \
    --nexus-src /app/FlashRT-Nexus \
    -j 4 \
    --sm 120 --cuda-tag 130 --python-minor 310 \
    --build-dir /app/FlashRT/build \
    --cpp-build-dir /tmp/flashrt-cpp \
    --nexus-build-dir /tmp/nexus-build \
    --runtime-version 1.0.0 --nexus-version 1.0.0
```

## `_bundle_build.sh` 做了什么

1. 从构建主机探测 SM / CUDA / Python / OS / arch
2. **FlashRT 根 cmake**（`/app/FlashRT`）：构建 `flash_rt_kernels` + `flash_rt_fa2` pybind 扩展
3. **FlashRT cpp/ 独立 cmake**（`/app/FlashRT/cpp`）：构建 `libflashrt_exec.so` + `libflashrt_runtime.so` + `libflashrt_cpp_pi05_c.so`
4. **Nexus cmake**（`/app/FlashRT-Nexus`）：构建 `libcapsule_nexus_flashrt.so`（链接 libflashrt_exec）
5. 把 2 个 Python 扩展 stage 到 `runtime/<env_key>/*.so`
6. 把 3 个 C 库 stage 到 `runtime/<env_key>/substrate/*.so`（子目录，validator 跳过）
7. 把 Nexus `serve/` Python 包 vendor 到 `substrate/nexus_python/`（改 import：`serve.*` → `nexus_python.*`）
8. 在 bundle 根 stage 精简版 `flash_rt/` Python 包（仅 Pi0.5 子集）
9. 写 `substrate/VERSION`（ABI 指纹的单一真相）
10. `ldd` 交叉校验：Nexus 库必须链接 bundle 内的 exec 库
11. 写 `.build/manifest-overlay.json`（含 `nexus_tag`、`features.nexus`）

## 校验

```sh
flashcli bundle validate bundles/pi05_libero_nexus
```

检查项：
- `flashcli-bundle.json` schema（format_version 3，protocol_version 1）
- `entry.run` / `entry.serve` 模块文件存在
- `python_abi: "310"` 与 runtime cell 后缀一致
- `runtime/<env_key>/*.so` 识别为 pybind 扩展（env_key 一致性）
- bundle 根存在 `flash_rt/` 目录
- （substrate 校验由 `_substrate_loader` 在运行时做，`validate` 不做）

## Smoke test

```sh
# 校验
flashcli bundle validate bundles/pi05_libero_nexus

# 拉权重（~1.6 GB）+ PaliGemma tokenizer + 安装依赖到 bundle venv
flashcli pull bundles/pi05_libero_nexus

# 单次推理（不传 --image 时用零图占位）
flashcli run bundles/pi05_libero_nexus \
    --prompt "pick up the red block" \
    --benchmark 5 --warmup 2

# Serve
flashcli serve bundles/pi05_libero_nexus --port 8080 &

curl http://127.0.0.1:8080/v1/substrate
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"pick up the red block"}]}'

curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=t0'
curl http://127.0.0.1:8080/v1/session/state
curl -X POST http://127.0.0.1:8080/v1/session/reset/t0
```

## 打包与发布

```sh
# 打包成 dist/ 下的可分发 zip
bash bundles/pi05_libero_nexus/pack.sh

# 校验打包后的 bundle
flashcli bundle validate dist/pi05_libero_nexus-*/

# 一键 FlashHub 发布（使用 release-matrix.env）
bash bundles/pi05_libero_nexus/release.sh
```

## 命名规范

| 制品 | 模板 | 示例 |
|---|---|---|
| Python 扩展 | `flash_rt_*-<fr_abi>-<env_key>.so` | `flash_rt_kernels-d0db114-sm120-cu130-linux-x86_64-py310.so` |
| FlashRT C 库 | `libflashrt_*-<fr_abi>-sm{SM}-cu{CU}-{os}-{arch}.so` | `libflashrt_exec-d0db114-sm120-cu130-linux-x86_64.so` |
| Nexus C 库 | `libcapsule_nexus_flashrt-fr<fr>.nx<nx>-sm{SM}-cu{CU}-{os}-{arch}.so` | `libcapsule_nexus_flashrt-frd0db114.nx8f13a3a-sm120-cu130-linux-x86_64.so` |

C 库**不带** `-pyNNN` —— 它们是纯 C，不依赖 Python ABI。它们放在 runtime cell 的 `substrate/` 子目录下，flashcli 现有 validator 只扫顶层 `*.so`，会跳过该子目录。

## 排错

| 症状 | 原因 | 修复 |
|---|---|---|
| `flashcli bundle validate` 报 `unrecognized native artifact filename` | 某个 C 库 `.so` 被放在 `runtime/<env>/` 顶层而非 `substrate/` | 移到 `substrate/` 下 |
| serve 启动时报 `libcapsule_nexus_flashrt does not link libflashrt_exec` | 构建后有人替换了 `libflashrt_exec.so` 的版本 | 用 `build.sh` 重新构建 |
| `flashcli run` 时 `ImportError: flash_rt_kernels` | 调用了错误 Python（host py311 而非 bundle py310） | 让 flashcli 自动 re-exec 进 bundle venv；不要绕过 |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled into this build` | FlashRT 根 CMake 配置时未加 `FA2_HDIMS="64;96;128;256"`（Pi0.5 SigLIP/decoder 需要 256）| `cmake -B /app/FlashRT/build -DFA2_HDIMS="64;96;128;256" -DFA2_DTYPES="fp16;bf16" -DGPU_ARCH=120 && cmake --build /app/FlashRT/build -j 4 --target flash_rt_fa2`，再重跑 `build.sh` |
| nvcc 被 OOM-kill（`cicc died due to signal 15`）| 构建主机内存 < 32 GB 或 `-j` 过高 | 降到 `-j 2` 或 `-j 1`；FA2 模板编译内存密集 |
