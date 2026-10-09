# Pi0.5 LIBERO Nexus

<p align="right"><a href="README.md">English</a> · <strong>简体中文</strong></p>

**Pi0.5** 视觉–语言–动作（VLA）策略，在 LIBERO 操作任务上微调，并通过 [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus) 提供服务。与 `pi05_libero` 同一策略，额外支持长驻**有状态 HTTP serve**（episode 快照 / 重置）与单次 **run** —— **全程无 Python**：Go host 通过 Nexus 内嵌 session 驱动 FlashRT pi05 的原生 model-runtime ABI。

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0@abi` · `@exec` |
| **权重** | [lerobot/pi05_libero_finetuned_v044](https://www.modelscope.cn/models/lerobot/pi05_libero_finetuned_v044)（ModelScope，约 7 GB） |
| **GPU** | NVIDIA **SM120**（Blackwell）· CUDA **13.x** |
| **运行时** | 原生 `.so`（无 Python 解释器、无 venv） |
| **能力** | `run` · `serve`（两个 variant 均支持） |

**输入：** 任务 prompt + RGB 图像（LIBERO 默认 **2** 路相机），可选本体 state。  
**输出：** 机器人策略动作序列（`run`）；HTTP act + episode 控制（`serve`）。

权重与 PaliGemma tokenizer 在首次 `pull` / `run` / `serve` 时拉取（不在 bundle zip 内）。`flashcli pull` 完成后推理完全离线。

## 后端（`@variant`）

同一份权重，两种执行后端，用 ref 后缀选择：

- **`@abi`** —— `native-abi`：host 进程内 `dlopen` model-runtime `.so` 并驱动（Nexus 内嵌 session），延迟最低。
- **`@exec`** —— `native-exec`：bundle 内自带的独立 Go HTTP 服务进程；`flashcli serve` 监管它并打印端点（不做反向代理）。

`flashcli pull` 是**按 variant** 的，权重缓存在 `.../<version>@<variant>/` 下。用哪个 variant 就 pull 哪个（或软链缓存共享同一 checkpoint）。

## 运行

```bash
flashcli pull flashcli-bundle/pi05_libero_nexus:1.0.0@abi

flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@abi \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg

# 同一模型，走独立 native-exec 服务器后端
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@exec \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

省略 `--image` 则使用占位帧；用 `--state` 传逗号分隔的浮点数设置本体状态（默认全 0）。

完整参数：`flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@abi --help`

## 服务

```bash
# native-abi：host 基于进程内 session 直接提供 HTTP 面
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@abi --host 0.0.0.0 --port 8080

# native-exec：host 监管 bundle 自带的 HTTP 服务并打印其端点
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@exec
```

Act（每请求一次 tick；`images[].data` 为 base64 RGB8，长度 `width*height*3`）：

```bash
curl -X POST http://127.0.0.1:8080/v1/act \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"pick up the red block and place it in the tray",
       "state":[0,0,0,0,0,0,0,0],
       "images":[{"width":224,"height":224,"data":"<base64-rgb>"},
                 {"width":224,"height":224,"data":"<base64-rgb>"}]}'
# -> {"actions":[...],"shape":[10,7]}
```

Episode 控制与探针：

```bash
curl -X POST http://127.0.0.1:8080/v1/session/snapshot -d '{"name":"after_pickup"}'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
curl http://127.0.0.1:8080/v1/session/state
curl http://127.0.0.1:8080/healthz
```

`POST /v1/chat/completions` 作为别名，载荷与 act 相同。

完整参数：`flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@abi --help`

## 参数

### `run`

| 参数 | 默认 | 说明 |
|------|------|------|
| `--prompt` | `pick up the red block and place it in the tray` | 任务指令 |
| `--image` | — | 逗号分隔的 RGB 路径（每路一张） |
| `--state` | *（全 0）* | 逗号分隔的本体状态 |
| `--num-views` | `2` | 相机路数（LIBERO 用 2） |
| `--stage-plan` | `full` | Nexus 阶段计划：`full` \| `context_action` |
| `--checkpoint` | *（自动）* | 覆盖缓存权重目录 |

### `serve`

| 参数 | 默认 | 说明 |
|------|------|------|
| `--host` | `127.0.0.1` | HTTP 绑定地址 |
| `--port` | `8080` | HTTP 绑定端口 |
| `--num-views` | `2` | 相机路数 |
| `--stage-plan` | `full` | Nexus 阶段计划：`full` \| `context_action` |
| `--warmup-prompt` | `pick up the red block and place it in the tray` | 可选 warmup tick 使用的 prompt |

## 与 `pi05_libero` 对比

| | `pi05_libero` | `pi05_libero_nexus` |
|---|---|---|
| 模式 | `run`（脚本 / 冒烟） | `run` + **`serve`**（有状态） |
| 运行时 | Python 3.12 venv | **原生 `.so`（无 Python）** |
| GPU cell | SM89 / SM120 | **仅 SM120 + cu130** |
| Episode API | — | 经 Nexus 的快照 / 重置 |

维护者构建文档：[`BUILD.zh-CN.md`](BUILD.zh-CN.md) / [`BUILD.md`](BUILD.md)。
