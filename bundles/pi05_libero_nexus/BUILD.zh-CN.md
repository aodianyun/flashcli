# pi05_libero_nexus — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：编译 FlashRT + FlashRT-Nexus 的 **native** 库，stage 到 `runtime/<env-key>/substrate/`，校验，冒烟 `run` / `serve`，打包，发布。**推理全程无 Python** —— bundle 通过 Nexus 内嵌 session 驱动 FlashRT pi05 的 model-runtime ABI。

**要求：** Linux · NVIDIA **SM120** · CUDA **13** 用户态 · cmake ≥ 3.24 · gcc ≥ 11 · CUTLASS（自动克隆）· FlashRT 源码 · FlashRT-Nexus 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
# Host: 安装 Go 二进制（release 或源码）
./install.sh --from-source          # 或 curl -fsSL <repo>/install.sh | sh
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_REPO=/path/to/FlashRT-Nexus
```

manifest 保留 `python_abi: "310"` 仅作运行单元的**标签**（`runtime/...-py310/`），**不会**创建 Python 解释器或 venv。**不要修改** FlashRT / Nexus 源码树——仅 stage 拷贝；三个 `.so` 须来自**同一** FlashRT/FlashRT-Nexus 构建。

## 1. 构建

`build.sh` 编译 Python-free 的 FA2 C 库（`flashrt_fa2_raw`）、FlashRT C 库（`libflashrt_exec`、`libflashrt_cpp_pi05_c`，native_v2）、以及 Nexus host（`libcapsule_nexus_flashrt`），再 stage 到 `runtime/<env-key>/substrate/` 并写 `substrate/VERSION`。**不再**产出 pybind 扩展或 vendored Python。

```bash
# 并行编译（FA2 模板吃内存，留些核给其它任务）
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  -j 7
```

仅打包（跳过 cmake，重新 stage 已有产物）：

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  --pack-only
```

产出：`runtime/sm120-cu130-linux-x86_64-py310/substrate/{libflashrt_exec-*,libflashrt_cpp_pi05_c-*,libcapsule_nexus_flashrt-*,libflashrt_fa2_raw-*,VERSION}` · `.build/manifest-overlay.json`

仅原生单元（无 `-py`）：`runtime/sm120-cu130-linux-x86_64/substrate/*`。构建还会编译 **native-exec 服务器**（bundle 自带、自包含 `native_exec/`）到 `runtime/<env>/bin/pi05_exec_server` 并拷贝 `exec_server.json`，通过 `@exec` 暴露同一模型。

可选覆盖：`--sm` · `--cuda-tag` · `--python-minor` · `--build-dir` · `--cpp-build-dir` · `--nexus-build-dir` · `--runtime-version` · `--nexus-version`。

## 2. 打包

```bash
bash bundles/pi05_libero_nexus/pack.sh
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus/dist"
```

打包树遵循 `release-matrix.env` 的 `RELEASE_PACK_FILES`（manifest、engine、辅助脚本、`flash_rt/`、含 `substrate/` 的 runtime cell）。

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
flashcli models envs "$BUNDLE"
```

## 4. 冒烟测试

权重来自 ModelScope（`lerobot/pi05_libero_finetuned_v044`，约 7 GB）+ `post_pull` 的 PaliGemma tokenizer。`pull` 之后推理保持离线。

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内可选

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg

flashcli run "$BUNDLE" --benchmark 5 --warmup 2

flashcli serve "$BUNDLE" --port 8080 &
curl http://127.0.0.1:8080/v1/substrate
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"x"}],
       "extras":{"images":[]}}'
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=t0'
curl -X POST http://127.0.0.1:8080/v1/session/reset/t0
```

打包后也请校验：`flashcli bundle validate dist/pi05_libero_nexus-*/`（路径以 `pack.sh` 实际产出为准）。

## 5. 发布

将 `dist/` 上传 FlashHub，ref 如 `flashcli-bundle/pi05_libero_nexus:<version>@abi` / `@exec`（按实际版本调整）。

```bash
bash bundles/pi05_libero_nexus/release.sh
# 或矩阵：
bash scripts/release_bundle.sh --bundle pi05_libero_nexus --clean
```

`release-matrix.env` 固定 SM120 / cu130 / py310。

## 说明

- **Substrate 布局：** 三个 C 库放在 `runtime/<env_key>/substrate/`；Go host 通过 Nexus 内嵌 session（`flashrt_loaded_model_open` + `nexus_embedded_*`）加载。运行时**没有** `_substrate_loader`/Python。
- **ABI 指纹：** `substrate/VERSION` 记录 FlashRT + Nexus commit；Nexus `.so` 应 `ldd` 链接到 bundle 内的 `libflashrt_exec.so`（并通过 manifest `preload` 保持可加载）。
- **FA2：** Pi0.5 的 encoder/decoder head_dim 为 `256`；默认完整 FA2 矩阵已覆盖。只有在确认无其它路径需要时才裁到 `-DFA2_HDIMS=256 -DFA2_DTYPES=bf16`。
- **与 `pi05_libero`：** 本 bundle 走生产有状态 serve；冒烟向脚本 bundle 保持独立。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `NativeEnvironmentNotSupportedError` | 为本机 env key 重编；`flashcli models envs "$BUNDLE"` |
| `unrecognized native artifact filename` | C 库放到 `substrate/`，不要放在 runtime cell 顶层 |
| `libcapsule_nexus_flashrt does not link libflashrt_exec` | 用 `build.sh` 整套重编（不要只替换其中一个库） |
| `no file matches {runtime_dir}/substrate/...` | 确认三个 `.so` 已 stage，且 manifest 的 `library`/`session_library`/`preload` glob 各只匹配一个文件 |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled` | FlashRT 用 `-DFA2_HDIMS="64;96;128;256"` 重配后编 FA2，再跑 `build.sh` |
| nvcc OOM（`cicc died due to signal 15`） | 降到 `-j 2` 或 `-j 1` |
| 权重下载失败 | 检查 ModelScope；或本地目录 `--checkpoint` |
