# Pi0.5 LIBERO Nexus

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Pi0.5 LIBERO VLA served through **FlashRT-Nexus native-abi**. No Python at inference: the host `dlopen`s the model-runtime `.so` and drives the Nexus embedded session.

| | |
|---|---|
| **Ref** | `flashcli-bundle/pi05_libero_nexus:1.0.3` |
| **Weights** | [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) (ModelScope, ~7 GB) |
| **GPU** | NVIDIA **SM120** (Blackwell) · CUDA **13.x** |
| **Python** | **none** (native runtime) |
| **Capabilities** | `run`, `serve` |

**Inputs:** task prompt + RGB images (LIBERO default **2** views), optional proprio state.
**Output:** action sequence (`run`); HTTP act + episode control (`serve`).

Weights and the PaliGemma tokenizer are pulled on first `pull` / `run` / `serve`; they are not in the bundle.

> `flashcli-bundle.exec.json` is an alternate native-exec example manifest. The published manifest is `flashcli-bundle.json` (native-abi).

## Run

```bash
flashcli run flashcli-bundle/pi05_libero_nexus:1.0.3 \
  --prompt "pick up the red block and place it in the tray" \
  --image /path/view0.jpg,/path/view1.jpg
```

## Serve

```bash
flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.3 --host 0.0.0.0 --port 8080
```

Full flags: `flashcli run flashcli-bundle/pi05_libero_nexus:1.0.3 --help` · `flashcli serve flashcli-bundle/pi05_libero_nexus:1.0.3 --help`

## Parameters

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

Build/release: [BUILD.md](BUILD.md).
