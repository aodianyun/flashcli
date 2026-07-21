# Pi0.5 LIBERO Nexus

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Pi0.5** 视觉–语言–动作（VLA）策略，在 LIBERO 操作任务上微调，并通过 [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus) 提供服务。与 `pi05_libero` 同一策略，额外支持长驻**有状态 HTTP serve**（episode 快照 / 重置）与 engine 模式 **run**。

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0` |
| **权重** | [lerobot/pi05_libero_finetuned_v044](https://www.modelscope.cn/models/lerobot/pi05_libero_finetuned_v044)（ModelScope，约 7 GB） |
| **GPU** | NVIDIA **SM120**（Blackwell）· CUDA **13.x** |
| **Python** | **3.10**（bundle venv） |
| **能力** | `run` · `serve` |

**输入：** 任务 prompt + RGB 图像（LIBERO 默认 **2** 路相机）。  
**输出：** 机器人策略动作序列（`run`）；OpenAI 风格 HTTP API + episode 控制（`serve`）。

权重与 PaliGemma tokenizer 在首次 `pull` / `run` / `serve` 时拉取（不在 bundle zip 内）。`flashcli pull` 完成后推理完全离线。

> **Serve 的 prompt：** Nexus 在**加载模型时**烧入任务指令（`--warmup-prompt` / manifest 默认）。`/v1/chat/completions` 的 `content` 在 act 时**被忽略**——只有 `extras.images` 进入策略。换任务需用不同 `--warmup-prompt` 重启 serve。

## 运行

```bash
flashcli pull flashcli-bundle/pi05_libero_nexus:1.0.0

flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

双路相机（默认 `--num-views 2`）：

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --num-views 2 \
  --image /path/view0.jpg,/path/view1.jpg
```

Benchmark（未传 `--image` 时用零图占位）：

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --prompt "pick up the red block" \
  --benchmark 5 --warmup 2
```

完整参数：`flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 --help`

## Serve

```bash
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0 --port 8080
```

每次请求一次 `act()`（`extras.images` 为 base64 JPEG 列表，一路相机一张）：

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"act 时忽略"}],
       "extras":{"images":["<base64-jpeg>","<base64-jpeg>"]}}'
```

Episode 控制与底座探测：

```bash
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=after_pickup'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
```

完整参数：`flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0 --help`

## 参数

### `run`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--prompt` | `pick up the red block and place it in the tray` | 任务指令 |
| `--image` | — | 逗号分隔的 RGB 路径（每路相机一张） |
| `--num-views` | `2` | 相机路数（LIBERO 为 2） |
| `--hardware` | `auto` | FlashRT 后端（`auto`、`rtx_sm120` 等） |
| `--autotune` | `3` | CUDA graph 调优次数（`0` 关闭） |
| `--use-fp8` | 开启 | 支持时使用 FP8 权重 |
| `--config` | `pi05` | FlashRT 配置名 |
| `--framework` | `torch` | FlashRT framework 后端 |
| `--checkpoint` | *（自动）* | 覆盖缓存权重目录 |

### `serve`

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--device` | `cuda:0` | Torch 设备 |
| `--num-views` | `2` | 相机路数 |
| `--precision` | `fp8` | `fp8` \| `fp16` |
| `--stage-plan` | `full` | Nexus stage plan：`full` \| `context_action` |
| `--hardware` | `auto` | FlashRT 后端 |
| `--capsule-dir` | *（空）* | capsule 落盘目录；空 = 仅内存 |
| `--warmup-prompt` | `pick up the red block and place it in the tray` | 加载时烧入的任务（见上文） |
| `--model-name` | `pi05-libero-nexus` | OpenAI API 模型 id |

## 与 `pi05_libero` 对比

| | `pi05_libero` | `pi05_libero_nexus` |
|---|---|---|
| 能力 | `run`（脚本 / 冒烟） | `run` + **`serve`**（有状态） |
| Python | 3.12 | **3.10** |
| GPU cell | SM89 / SM120 | 仅 **SM120 + cu130** |
| Episode API | — | Nexus snapshot / reset |

维护者构建文档：[`BUILD.md`](BUILD.md) / [`BUILD.zh-CN.md`](BUILD.zh-CN.md)。
