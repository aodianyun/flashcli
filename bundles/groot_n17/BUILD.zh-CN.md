# groot_n17 — 构建与冒烟测试

<p align="right"><a href="BUILD.md">English</a> · <strong>简体中文</strong></p>

```bash
cd /path/to/flashcli
pip install -e ./flashcli-bundle -e .
export FLASHRT_REPO=/path/to/FlashRT
```

本 bundle 使用 **Python 3.10**（`python_abi: "310"`）。FlashRT 原生 `.so` 须按 **py310** 编译，与 bundle venv 一致。

**无需手动安装 Python 3.10。** `build.sh` 会从 `flashcli-bundle.json` 读取 `python_abi`，自动查找匹配的解释器；若本机没有则自动安装（standalone 压缩包或 apt）。可用 `FLASHCLI_PY310_BIN` 或 `--python-bin` 覆盖；用 `--no-install-python` 或 `FLASHCLI_AUTO_INSTALL_BUILD_PYTHON=0` 关闭自动安装。

## 1. 编译

`build.sh` 会把 Isaac-GR00T 推理代码 vendoring 到 bundle 根目录的 `gr00t/`（**不** `pip install gr00t`）。`activate_bundle` 会把 bundle 根目录 prepend 到 `PYTHONPATH`，预处理与 FlashRT `denormalize_action` 共用同一份 vendored 源码。

```bash
bash bundles/groot_n17/build.sh \
  --repo-root "$FLASHRT_REPO" \
  -j "$(nproc)"
```

CMake 使用 `-DFA2_HDIMS="64;96;128" -DFA2_DTYPES="fp16;bf16"`。N1.7 的 VLM backbone（ViT + VL self-attn FA2）需要 **64**，DiT 注意力需要 **96;128**。

产物：`gr00t/`（vendored）、`runtime/sm120-cu130-linux-x86_64-py310/*.so`、`flash_rt/`、`.build/manifest-overlay.json`

FlashRT 已编译时可跳过 cmake：

```bash
bash bundles/groot_n17/build.sh \
  --repo-root "$FLASHRT_REPO" \
  --pack-only
```

仅重新 vendoring（不重编 FlashRT）：

```bash
bash bundles/groot_n17/vendor_gr00t.sh
python3 bundles/groot_n17/_verify_gr00t_vendor.py
```

## 2. 打包

```bash
bash bundles/groot_n17/pack.sh
export BUNDLE="$(pwd)/bundles/groot_n17/dist"
```

`pack.sh` copies `gr00t/` into `dist/` (see `RELEASE_PACK_FILES` in `release-matrix.env`). If `flashcli run` reports `No module named 'gr00t'`, the deployed bundle is missing vendored `gr00t/` — re-run `build.sh` (vendors `gr00t/`) then `pack.sh`, or `flashcli bundle validate "$BUNDLE"`.

## 3. 校验

```bash
flashcli bundle validate "$BUNDLE"
```

## 4. 冒烟测试

`flashcli pull` 仅下载 GR00T N1.7 权重（无额外 tokenizer）。

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 如需要

flashcli pull "$BUNDLE"

flashcli run "$BUNDLE" \
  --prompt "put the blue block in the green bowl" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --image /path/v0.jpg,/path/v1.jpg

flashcli run "$BUNDLE" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2

flashcli run "$BUNDLE" \
  --embodiment-tag oxe_droid_relative_eef_relative_joint \
  --num-views 2 \
  --benchmark 5
```

升级 bundle manifest 或 vendored `gr00t/` 后，请重建 runtime venv：

```bash
rm -rf ~/.flashcli/runtimes/groot_n17-local-*/venv
flashcli run "$BUNDLE" ...
```

## 排错（构建）

| 现象 | 处理 |
|------|------|
| `GemmRunner missing fp8_nt_dev` | 重编 FlashRT 或使用 `_groot_compat.py` shim |
| `vendor-gr00t` 克隆失败 | 设置 `FLASHCLI_GIT_PROXY` 或 `FLASHCLI_GR00T_SRC=/path/to/Isaac-GR00T` |
| vendored gr00t 布局不完整 | 重跑 `vendor_gr00t.sh`；查看 `_verify_gr00t_vendor.py` 输出 |
| `.so` Python ABI 不匹配 | 重新执行 `build.sh`（勿仅用 `--pack-only`），确保 py310 原生编译 |
| 关闭自动安装后 `No Python py310 found` | 去掉 `--no-install-python`，或设置 `FLASHCLI_PY310_BIN` |
| 动作不合理 | `embodiment_tag` 或 `--num-views` 错误；尽量用真实图像 |
| 运行时 CUDA OOM | 预处理会在加载 FlashRT 前释放 Gr00tPolicy；关闭其他占 GPU 进程 |

### Vendored gr00t（Isaac-GR00T）

N1.7 **不再**通过 pip 安装 Isaac-GR00T，而是：

1. `vendor_gr00t.sh` 浅克隆 ref `ab88b50...`（不拉仿真 submodule）到 `bundles/groot_n17/gr00t/`
2. `gr00t/VENDOR.json` 记录 repo、ref、commit，便于追溯
3. 运行时 pip 依赖（`torch==2.7.1`、`transformers==4.57.3`、`tyro` 等）仅由 `flashcli-bundle.json` 声明；额外 vendored 专用依赖见 `gr00t-inference-requirements.txt`

GitHub 不可达时：

```bash
export FLASHCLI_GIT_PROXY=https://mirror.ghproxy.com/
# 或指定本地/离线源码：
export FLASHCLI_GR00T_SRC=/path/to/Isaac-GR00T
bash bundles/groot_n17/vendor_gr00t.sh
```

源码缓存：`~/.flashcli/cache/isaac-gr00t-src/<git-ref>/`（设置 `FLASHCLI_GR00T_SRC` 时跳过）。

升级上游 pin：修改 `vendor_gr00t.sh` 中的 `GR00T_REF`，重新 vendoring、跑 `_verify_gr00t_vendor.py`，再 build/pack。
