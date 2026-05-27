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

## 目录（v2 扁平，对齐 `pi05_libero`）

```text
qwen_nvfp4/
├── flashcli-bundle.json
├── build.sh
├── run.py / serve.py
├── _qwen_util.py / _flashrt_serve.py
├── flash_rt/                 # 构建产物
├── flash_rt_kernels-*.so
├── checkpoint/qwen3/
├── checkpoint/qwen36/
└── mtp_fp8/                  # 仅 qwen36
```

## 构建

```bash
bash bundles/qwen_nvfp4/build.sh --repo-root /path/to/FlashRT -j "$(nproc)"
flashcli bundle validate bundles/qwen_nvfp4
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
