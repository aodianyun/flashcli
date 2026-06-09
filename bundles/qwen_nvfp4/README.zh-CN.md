# qwen_nvfp4

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="QUICKSTART.zh-CN.md">快速上手</a></p>

一个 **SM120 NVFP4** FlashHub repo；catalog 用多个 preset + `bundle_variant` 区分 Qwen3-8B / Qwen3.6-27B 权重。

## 分工

```text
┌─────────────────────────────────────────────────────────┐
│  FlashHub repo（format_version 3）                       │
│  flashcli-bundle.json → runtime: { env_key: path }       │
│  flash_rt/ + runtime/<env-key>/*.so + run.py / serve.py │
└─────────────────────────────────────────────────────────┘
          ▲                           ▲
          │ 同一 bundle.repo            │ bundle_variant
┌─────────┴──────────┐       ┌─────────┴──────────┐
│ qwen3-8b-nvfp4     │       │ qwen36-27b-nvfp4   │
└────────────────────┘       └────────────────────┘
```

权重按 **preset 名** 缓存：`~/.flashcli/models/qwen3-8b-nvfp4/checkpoint/` 等（不在 bundle 内）。

### Hugging Face 权重

| variant | 主权重 | MTP（仅 qwen36） |
|---------|--------|------------------|
| `qwen3` | [kaitchup/Qwen3-8B-NVFP4](https://huggingface.co/kaitchup/Qwen3-8B-NVFP4) | — |
| `qwen36` | [prithivMLmods/Qwen3.6-27B-NVFP4](https://huggingface.co/prithivMLmods/Qwen3.6-27B-NVFP4) | [Qwen/Qwen3.6-27B-FP8](https://huggingface.co/Qwen/Qwen3.6-27B-FP8) 的 `mtp.safetensors` |

## 目录（开发树）

```text
qwen_nvfp4/
├── flashcli-bundle.json   # format_version: 3, runtime: { ... }
├── build.sh / pack.sh
├── run.py / serve.py / ...
├── flash_rt/
├── lib/ 或 runtime/       # 本地 build / pack 产出
└── dist/                  # 发布：源码树 + runtime/<env-key>/
```

## 发布构建（维护者）

**SM120 × cu130 × py312**（见 `release-matrix.env`）。

```bash
cd flashcli/bundles/qwen_nvfp4
bash release.sh --clean
```

上传 `dist/` 到 FlashHub → 更新 `models.yaml` 中两个 preset 的 **`bundle.repo`**（同一 URL）。

详见 [docs/runtime-matrix.zh-CN.md](../../docs/runtime-matrix.zh-CN.md#qwen_nvfp4-sm120--cu130)。

## 运行

命令速查见 **[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)**。

```bash
flashcli run qwen3-8b-nvfp4 --prompt "你好"
flashcli serve qwen36-27b-nvfp4 --port 8000 --K 6
```

本地未用 FlashHub 时：

```bash
export BUNDLE="$(pwd)/bundles/qwen_nvfp4"
flashcli run qwen3-8b-nvfp4 --bundle "$BUNDLE" --prompt "你好"
```
