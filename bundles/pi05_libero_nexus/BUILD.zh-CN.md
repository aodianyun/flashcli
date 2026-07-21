# pi05_libero_nexus — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

维护者流程：编译 FlashRT + FlashRT-Nexus native，stage 到 `runtime/<env-key>/`（含 `substrate/`），校验，冒烟 `run` / `serve`，打包，发布。

**要求：** Linux · NVIDIA **SM120** · CUDA **13** 用户态 · cmake ≥ 3.24 · gcc ≥ 11 · **Python 3.10** · FlashRT 源码 · FlashRT-Nexus 源码 · flashcli 开发环境。

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export BUNDLE="$(pwd)/bundles/pi05_libero_nexus"
export FLASHRT_REPO=/path/to/FlashRT
export NEXUS_REPO=/path/to/FlashRT-Nexus
```

本 bundle 使用 **Python 3.10**（`python_abi: "310"`）。native `.so` 须与 py310 匹配。**不要修改** FlashRT / Nexus 源码树——仅 stage 拷贝；`flash_rt/` 与 `.so` 须来自**同一** FlashRT commit。

## 1. 构建

`build.sh` 编译 FlashRT pybind + C 库 + Nexus capsule，stage 带标签 `.so`，vendor 精简 `flash_rt/` 与 `substrate/nexus_python/`，写入 `substrate/VERSION`。

```bash
# 32 GB 内存主机建议 -j 4（FA2 模板编译很吃内存）
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  -j 4
```

仅打包（跳过 cmake，重新 stage 已有产物）：

```bash
bash bundles/pi05_libero_nexus/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --nexus-src "$NEXUS_REPO" \
  --pack-only
```

产出：`flash_rt/` · `runtime/sm120-cu130-linux-x86_64-py310/*.so` · `runtime/.../substrate/{*.so,nexus_python/,VERSION}` · `.build/manifest-overlay.json`

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

将 `dist/` 上传 FlashHub，ref 如 `flashcli-bundle/pi05_libero_nexus:1.0.0`（按实际版本调整）。

```bash
bash bundles/pi05_libero_nexus/release.sh
# 或矩阵：
bash scripts/release_bundle.sh --bundle pi05_libero_nexus --clean
```

`release-matrix.env` 固定 SM120 / cu130 / py310。

## 说明

- **Substrate 布局：** C 库放在 `runtime/<env_key>/substrate/`（validator 只扫顶层 `*.so`；运行时由 `_substrate_loader` 加载并做 ABI 校验）。
- **ABI 指纹：** `substrate/VERSION` 记录 FlashRT + Nexus commit；Nexus `.so` 必须 `ldd` 链接到 bundle 内的 `libflashrt_exec.so`。
- **FA2：** Pi0.5 需要 `FA2_HDIMS` 含 `256`（SigLIP / decoder）。
- **与 `pi05_libero`：** 本 bundle 走生产有状态 serve；冒烟向脚本 bundle 保持独立。

## 故障排查（构建）

| 现象 | 处理 |
|------|------|
| `NativeEnvironmentNotSupportedError` | 为本机 env key 重编；`flashcli models envs "$BUNDLE"` |
| `unrecognized native artifact filename` | C 库放到 `substrate/`，不要放在 runtime cell 顶层 |
| `libcapsule_nexus_flashrt does not link libflashrt_exec` | 用 `build.sh` 整套重编（不要只替换其中一个库） |
| `ImportError: flash_rt_kernels` | 让 flashcli re-exec 进 bundle py310 venv；不要绕过 |
| `fvk_attention_fa2: head_dim<=256=256 was not compiled` | FlashRT 用 `-DFA2_HDIMS="64;96;128;256"` 重配后编 FA2，再跑 `build.sh` |
| nvcc OOM（`cicc died due to signal 15`） | 降到 `-j 2` 或 `-j 1` |
| 权重下载失败 | 检查 ModelScope；或本地目录 `--checkpoint` |
