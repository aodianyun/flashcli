# qwen_nvfp4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

一个 **SM120 NVFP4** runtime zip；catalog 用多个 preset + `bundle_variant` 区分 Qwen3-8B / Qwen3.6-27B 权重。

## 分工

```text
┌─────────────────────────────────────────────────────────┐
│  bundle.zip（multi-env：lib/*-sm120-cu130-*-py310|311|312）│
│  flashcli-bundle.json → variants: { qwen3, qwen36 }      │
│  flash_rt/ + lib/*.so + run.py / serve.py                │
└─────────────────────────────────────────────────────────┘
          ▲                           ▲
          │ 同一 bundle.zip             │ bundle_variant
┌─────────┴──────────┐       ┌─────────┴──────────┐
│ qwen3-8b-nvfp4     │       │ qwen36-27b-nvfp4   │
└────────────────────┘       └────────────────────┘
```

权重按 **preset 名** 缓存：`~/.flashcli/models/qwen3-8b-nvfp4/checkpoint/` 等（不打进 zip）。

### Hugging Face 权重

| variant | 主权重 | MTP（仅 qwen36） |
|---------|--------|------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) 的 `mtp.safetensors` |

`JunHowie/Qwen3-8B-Instruct-2512-SFT-NVFP4` 在 HF 上已不可用。

## 目录（v2，`lib/` 原生矩阵）

```text
qwen_nvfp4/
├── flashcli-bundle.json   # native_layout: matrix, native_matrix: [...]
├── build.sh / pack.sh
├── run.py / serve.py / _qwen_util.py
├── _serve_backend.py        # 统一 ServeChatBackend 协议
├── _backend_qwen3.py / _backend_qwen36_agent.py
├── _flashrt_qwen3.py / _flashrt_qwen36_agent.py   # FlashRT loaders
├── flash_rt/
├── lib/
│   ├── flash_rt_kernels-*-sm120-cu130-linux-x86_64-py310.so
│   ├── flash_rt_fa2-*-py311.so
│   └── …（cu130 × py310/311/312，每档 **kernels + fa2**；NVFP4 在 kernels 内）
└── dist/
    └── flashcli-bundle-qwen_nvfp4-{abi}-sm120-multi-linux-x86_64-{timestamp}.zip
```

**不要**把 `flash_rt_*.so` 放在 bundle 根目录。

## 发布构建（维护者）

与 [`pi05_libero`](../pi05_libero/README.zh-CN.md) 相同：**一个 multi-env zip**（sm120 × cu130 × py310/311/312）。

```bash
cd flashcli/bundles/qwen_nvfp4
bash release.sh --clean
# 等价：bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

需 **Linux + Docker + GPU**（默认 `25.10-py3`）或宿主机 `--native` + CUDA 13。**无 cu124 线**。

后台 + 日志：

```bash
bash scripts/run_bg.sh --name release-qwen -- \
  bash scripts/release_bundle.sh --bundle qwen_nvfp4 --clean
```

预检：`bash ../../scripts/build_release_matrix.sh --bundle qwen_nvfp4 --check-only`

产物示例：`dist/flashcli-bundle-qwen_nvfp4-{abi}-sm120-multi-linux-x86_64-{时间戳}.zip` → 上传 CDN → 更新 `models.yaml` 中两个 preset 的 `bundle.zip`。

单格本地开发（当前 Python 一档）：

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root "$FLASHRT_REPO" -j "$(nproc)"
# 或仅 stage：--pack-only
```

详见 [docs/runtime-matrix.zh-CN.md](../../docs/runtime-matrix.zh-CN.md#qwen_nvfp4-sm120--cu130)。

## 运行

```bash
flashcli run qwen3-8b-nvfp4 --prompt "Hello"
flashcli serve qwen3-8b-nvfp4 --host 0.0.0.0 --port 8000 --max-seq 2048 --max-q-seq 1024 --warmup-preset auto
flashcli run qwen36-27b-nvfp4 --prompt "Hi" --K 4
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 4 --max-seq 262208 --warmup-preset agent
```

本地未用 CDN 时：

```bash
flashcli run qwen3-8b-nvfp4 --bundle "$(pwd)/bundles/qwen_nvfp4" --prompt "你好"
```
