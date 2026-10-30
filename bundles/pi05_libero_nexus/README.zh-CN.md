# Pi0.5 LIBERO Nexus

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

Pi0.5 LIBERO VLA，通过 **FlashRT-Nexus native-abi** 运行。推理无 Python：host `dlopen` model-runtime `.so` 并驱动 Nexus 内嵌 session。

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.3` |
| **权重** | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) (ModelScope, ~7 GB) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **none** (native runtime) |
| **能力** | `run`, `serve` |

**输入：** 任务 prompt + RGB 图像（LIBERO 默认 **2** 路），可选 proprio state。
**输出：** 动作序列（`run`）；HTTP act + episode control（`serve`）。

权重与 PaliGemma tokenizer 在首次 `pull` / `run` / `serve` 时下载；不包含在 bundle 中。

> `flashcli-bundle.exec.json` 是 native-exec 备用示例 manifest；发布使用的是 `flashcli-bundle.json`（native-abi）。

## 运行

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.3 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

## 服务

```bash
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.3 --host 0.0.0.0 --port 8080
```

完整参数：`flashcli run flashcli-bundle/pi05_libero_nexus:1.0.3 --help` · `flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.3 --help`

## 参数

### `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `pick up the red block and place it in the tray` | Natural-language task instruction. |
| `--image` | — | Comma-separated RGB image paths (one per view). |
| `--state` | — | Comma-separated proprio state (defaults to zeros). |
| `--num-views` | `2` | Number of camera views. |
| `--stage-plan` | `full` | Nexus stage plan: full | context_action. |

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | HTTP bind host. |
| `--port` | `8080` | HTTP bind port. |
| `--num-views` | `2` | Number of camera views. |
| `--stage-plan` | `full` | Nexus stage plan: full | context_action. |
| `--warmup-prompt` | `pick up the red block and place it in the tray` | Prompt for the optional warmup tick. |

构建/发布：[BUILD.zh-CN.md](BUILD.zh-CN.md)。
