# Pi0.5 LIBERO Nexus

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Pi0.5** vision–language–action (VLA) policy fine-tuned on LIBERO, served via [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus). Same policy as `pi05_libero`, plus long-running **stateful HTTP serve** (episode snapshot / reset) and single-shot **run** — **entirely without Python**: the Go host drives the FlashRT pi05 native model-runtime ABI through the Nexus embedded session.

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0@abi` · `@exec` |
| **Weights** | [lerobot/pi05_libero_finetuned_v044](https://www.modelscope.cn/models/lerobot/pi05_libero_finetuned_v044) (ModelScope, ~7 GB) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Runtime** | Native `.so` (no Python interpreter, no venv) |
| **Capabilities** | `run` · `serve` (both variants) |

**Inputs:** task prompt + RGB images (LIBERO default **2** views), optional proprio state.  
**Output:** robot policy action sequence (`run`); HTTP act + episode control (`serve`).

Weights and the PaliGemma tokenizer are pulled on first `pull` / `run` / `serve` (not in the bundle zip). After `flashcli pull`, inference is fully offline.

## Backends (`@variant`)

Same weights, two execution backends selected by the ref suffix:

- **`@abi`** — `native-abi`: the host `dlopen`s the model-runtime `.so` and drives it in-process (Nexus embedded session). Lowest latency.
- **`@exec`** — `native-exec`: a standalone Go HTTP server shipped in the bundle run as a separate process; `flashcli serve` supervises it and prints the endpoint (no reverse proxy).

`flashcli pull` is **per-variant**; weights are cached under `.../<version>@<variant>/`. Pull each variant you use (or symlink the cache to share the checkpoint).

## Run

```bash
flashcli pull flashcli-bundle/pi05_libero_nexus:1.0.0@abi

flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@abi \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg

# same, through the standalone native-exec server backend
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@exec \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

Omit `--image` to use placeholder frames; pass `--state` as comma-separated floats to set proprioception (defaults to zeros).

Full flags: `flashcli run flashcli-bundle/pi05_libero_nexus:1.0.0@abi --help`

## Serve

```bash
# native-abi: the host serves the HTTP surface over the in-process session
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@abi --host 0.0.0.0 --port 8080

# native-exec: the host supervises the bundle's HTTP server and prints its endpoint
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@exec
```

Act (one tick per request; `images[].data` = base64 RGB8, `width*height*3` bytes):

```bash
curl -X POST http://127.0.0.1:8080/v1/act \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"pick up the red block and place it in the tray",
       "state":[0,0,0,0,0,0,0,0],
       "images":[{"width":224,"height":224,"data":"<base64-rgb>"},
                 {"width":224,"height":224,"data":"<base64-rgb>"}]}'
# -> {"actions":[...],"shape":[10,7]}
```

Episode control + probes:

```bash
curl -X POST http://127.0.0.1:8080/v1/session/snapshot -d '{"name":"after_pickup"}'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
curl http://127.0.0.1:8080/v1/session/state
curl http://127.0.0.1:8080/healthz
```

`POST /v1/chat/completions` is accepted as an alias and takes the same act payload.

Full flags: `flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.0@abi --help`

## Parameters

### `run`

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | `pick up the red block and place it in the tray` | Task instruction |
| `--image` | — | Comma-separated RGB paths (one per view) |
| `--state` | *(zeros)* | Comma-separated proprio state |
| `--num-views` | `2` | Camera views (LIBERO uses 2) |
| `--stage-plan` | `full` | Nexus stage plan: `full` \| `context_action` |
| `--checkpoint` | *(auto)* | Override cached weight directory |

### `serve`

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | HTTP bind host |
| `--port` | `8080` | HTTP bind port |
| `--num-views` | `2` | Camera views |
| `--stage-plan` | `full` | Nexus stage plan: `full` \| `context_action` |
| `--warmup-prompt` | `pick up the red block and place it in the tray` | Prompt for the optional warmup tick |

## vs `pi05_libero`

| | `pi05_libero` | `pi05_libero_nexus` |
|---|---|---|
| Mode | `run` (script / smoke) | `run` + **`serve`** (stateful) |
| Runtime | Python 3.12 venv | **native `.so` (no Python)** |
| GPU cell | SM89 / SM120 | **SM120 + cu130** only |
| Episode API | — | snapshot / reset via Nexus |

Maintainer build docs: [`BUILD.md`](BUILD.md) / [`BUILD.zh-CN.md`](BUILD.zh-CN.md).
