# Pi0.5 LIBERO Nexus

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Pi0.5** vision–language–action (VLA) policy fine-tuned on LIBERO, served via [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus). Same policy as `pi05_libero`, plus long-running **stateful HTTP serve** (episode snapshot / reset) and engine-mode **run**.

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0` |
| **Weights** | [lerobot/pi05_libero_finetuned_v044](https://www.modelscope.cn/models/lerobot/pi05_libero_finetuned_v044) (ModelScope, ~7 GB) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **3.10** (bundle venv) |
| **Capabilities** | `run` · `serve` |

**Inputs:** task prompt + RGB images (LIBERO default **2** views).  
**Output:** robot policy action sequence (`run`); OpenAI-style HTTP API + episode control (`serve`).

Weights and PaliGemma tokenizer are pulled on first `pull` / `run` / `serve` (not in the bundle zip). After `flashcli pull`, inference is fully offline.

> **Serve prompt:** Nexus bakes the task instruction at **model load** (`--warmup-prompt` / manifest default). `/v1/chat/completions` message `content` is **ignored** at act time — only `extras.images` feed the policy. To change the task, restart serve with a different `--warmup-prompt`.

## Run

```bash
flashcli pull flashcli-bundle/pi05_libero_nexus:1.0.0

flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

Two views (default `--num-views 2`):

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --num-views 2 \
  --image /path/view0.jpg,/path/view1.jpg
```

Benchmark (placeholder zeros if `--image` omitted):

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 \
  --prompt "pick up the red block" \
  --benchmark 5 --warmup 2
```

Full flags: `flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0 --help`

## Serve

```bash
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0 --port 8080
```

One `act()` per request (`extras.images` = base64 JPEG list, one per view):

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"ignored at act time"}],
       "extras":{"images":["<base64-jpeg>","<base64-jpeg>"]}}'
```

Episode control + substrate probe:

```bash
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=after_pickup'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
```

Full flags: `flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0 --help`

## Parameters

### `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `pick up the red block and place it in the tray` | Task instruction |
| `--image` | — | Comma-separated RGB paths (one per view) |
| `--num-views` | `2` | Camera views (LIBERO uses 2) |
| `--hardware` | `auto` | FlashRT backend (`auto`, `rtx_sm120`, …) |
| `--autotune` | `3` | CUDA graph autotune trials (`0` disables) |
| `--use-fp8` | on | Load FP8 weights when supported |
| `--config` | `pi05` | FlashRT model config name |
| `--framework` | `torch` | FlashRT framework backend |
| `--checkpoint` | *(auto)* | Override cached weight directory |

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | Torch device |
| `--num-views` | `2` | Camera views |
| `--precision` | `fp8` | `fp8` \| `fp16` |
| `--stage-plan` | `full` | Nexus stage plan: `full` \| `context_action` |
| `--hardware` | `auto` | FlashRT backend |
| `--capsule-dir` | *(empty)* | Persist capsules to disk; empty = in-memory only |
| `--warmup-prompt` | `pick up the red block and place it in the tray` | Task baked at load (see note above) |
| `--model-name` | `pi05-libero-nexus` | OpenAI API model id |

## vs `pi05_libero`

| | `pi05_libero` | `pi05_libero_nexus` |
|---|---|---|
| Mode | `run` (script / smoke) | `run` + **`serve`** (stateful) |
| Python | 3.12 | **3.10** |
| GPU cell | SM89 / SM120 | **SM120 + cu130** only |
| Episode API | — | snapshot / reset via Nexus |

Maintainer build docs: [`BUILD.md`](BUILD.md) / [`BUILD.zh-CN.md`](BUILD.zh-CN.md).
