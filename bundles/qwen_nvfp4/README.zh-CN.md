# qwen_nvfp4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

> **内部草稿。** 一个 SM120 runtime 制品；catalog 用多个 preset + `bundle_variant` 区分 Qwen3 / Qwen3.6。

## 工业级分工

```text
┌─────────────────────────────────────────────────────────┐
│  bundle.zip / bundles/qwen_nvfp4/   （一份 runtime）      │
│  flashcli-bundle.json → variants: { qwen3, qwen36 }      │
│  flash_rt/ + flash_rt_kernels-*.so + run.py / serve.py   │
└─────────────────────────────────────────────────────────┘
          ▲                           ▲
          │ bundle.path 相同            │ bundle_variant
┌─────────┴──────────┐       ┌─────────┴──────────┐
│ preset             │       │ preset             │
│ qwen3-8b-nvfp4     │       │ qwen36-27b-nvfp4   │
│ bundle_variant:    │       │ bundle_variant:    │
│   qwen3            │       │   qwen36           │
└────────────────────┘       └────────────────────┘
```

权重缓存按 **preset 名** 分开：`~/.flashcli/models/qwen3-8b-nvfp4/checkpoint/` 与 `.../qwen36-27b-nvfp4/checkpoint/`。

### Hugging Face 权重（已核对存在、公开）

| variant | 主权重 | MTP（仅 qwen36） |
|---------|--------|------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4)（`compressed-tensors` NVFP4，基座 `Qwen/Qwen3-8B`） | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4)（FlashRT 文档对齐） | [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) 中的 `mtp.safetensors` |

旧配置 `JunHowie/Qwen3-8B-Instruct-2512-SFT-NVFP4` 在 HF 上已不可用，勿再使用。

## 目录（v2，与 `pi05_libero` 一致：原生库在 `lib/`）

```text
qwen_nvfp4/
├── flashcli-bundle.json
├── build.sh
├── run.py / serve.py
├── _qwen_util.py / _flashrt_serve.py
├── flash_rt/                 # Python runtime（构建产物）
├── lib/                      # 必须：带环境标签的 *.so
│   ├── flash_rt_kernels-*-sm120-cu130-…-py312.so
│   ├── flash_rt_fa2-*.so
│   └── flash_rt_fp4-*.so       # NVFP4（SM120）
├── checkpoint/qwen3/
├── checkpoint/qwen36/
└── mtp_fp8/                  # 仅 qwen36
```

**不要**把 `flash_rt_*.so` 放在 bundle 根目录；`build.sh` 会写入 `lib/` 并刷新 `modules[].file` 为 `lib/…`。

## 构建

```bash
flashcli bundle build bundles/qwen_nvfp4 --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli bundle validate bundles/qwen_nvfp4
```

依赖：`cmake`、`nvcc`、`git`、`tar`（无 `rsync` 时用 tar 拷贝 `flash_rt/`）。CMake 已成功时可用 `--pack-only` 只打 stage：

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /app/FlashRT --pack-only
```

## 运行（推荐：用 catalog preset，无需每次 `--model`）

```bash
flashcli run qwen3-8b-nvfp4 --prompt "你好"
flashcli run qwen36-27b-nvfp4 --prompt "解释量子纠缠" --K 6
flashcli serve qwen36-27b-nvfp4 --port 8000
```

本地未写入 catalog 时：

```bash
flashcli run qwen_nvfp4 --bundle bundles/qwen_nvfp4 --model qwen3 --prompt "你好"
```

`--model` 仅用于覆盖 `models.yaml` 里的 `bundle_variant`（调试）。
