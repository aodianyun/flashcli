# pi05_libero_nexus

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

**Pi0.5 LIBERO VLA — stateful serving via [FlashRT-Nexus](https://github.com/LiangSu8899/FlashRT-Nexus).**

| | |
|---|---|
| **FlashHub ref** | `flashcli-bundle/pi05_libero_nexus:1.0.0` |
| **Weights** | [`lerobot/pi05_libero_finetuned_v044`](https://huggingface.co/lerobot/pi05_libero_finetuned_v044) (~7 GB, pulled automatically) |
| **Substrate** | FlashRT `d0db114` + Nexus `8f13a3a` (composite tag `frd0db114.nx8f13a3a`) |
| **Bundle format** | [flashcli-model-bundle v3](../../docs/bundle_publish_standard.md) |

This bundle wraps the Pi0.5 LIBERO policy with the FlashRT inference engine and adds the FlashRT-Nexus serving substrate on top. Compared to the legacy `pi05_libero` bundle (single-shot script inference), this bundle exposes:

- A long-running **HTTP serve mode** with `/v1/chat/completions` (one `act()` per request).
- **Episode control**: `POST /v1/session/snapshot`, `POST /v1/session/reset/{capsule}` for warm-start / undo / episode reset via Nexus capsule verbs.
- A substrate inspection endpoint: `GET /v1/substrate`.
- A standard **engine-mode run** for single-shot inference and benchmarking.

Both `flashcli run` and `flashcli serve` are supported from the same bundle.

> **Prompt handling**: the Pi0.5 Nexus producer **bakes the task instruction at model load time**; it does not expose a dynamic prompt port. The instruction is fixed to the manifest's `model.prompt` (overridable via the `--warmup_prompt` serve option). The `content` field of `/v1/chat/completions` messages is **ignored** at inference time — only `extras.images` flows into the policy. To switch tasks, restart the server with a different `--warmup_prompt`.

## Supported environment

| Field | Value |
|---|---|
| Python ABI | `310` (CPython 3.10) |
| GPU | SM 120 (Blackwell: RTX 50 series) |
| CUDA | 13.0 |
| OS / arch | linux / x86_64 |
| Runtime cell | `sm120-cu130-linux-x86_64-py310` |

## Quickstart

```sh
# 1) Validate bundle layout (offline, no GPU needed)
flashcli bundle validate bundles/pi05_libero_nexus

# 2) Pull weights + PaliGemma tokenizer + install Python deps into bundle venv
flashcli pull bundles/pi05_libero_nexus

# 3) One-shot inference
flashcli run bundles/pi05_libero_nexus \
    --prompt "pick up the red block and place it in the tray" \
    --image cam0.jpg,cam1.jpg

# 4) Long-running stateful server
flashcli serve bundles/pi05_libero_nexus --port 8080 &

# In another terminal:
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"pick up the red block"}],
         "extras":{"images":["<base64-jpeg>","<base64-jpeg>"]}}'

# Episode control:
curl -X POST 'http://127.0.0.1:8080/v1/session/snapshot?name=after_pickup'
curl -X POST http://127.0.0.1:8080/v1/session/reset/after_pickup
curl http://127.0.0.1:8080/v1/substrate
```

After `flashcli pull`, all inference paths work **fully offline** — no further downloads, no pip installs at run time.

## Layout

```
bundles/pi05_libero_nexus/
├── flashcli-bundle.json               # manifest (entry.run + entry.serve, substrate block)
├── flash_rt/                          # vendored slim FlashRT Python pkg (Pi0.5 subset)
├── runtime/
│   └── sm120-cu130-linux-x86_64-py310/
│       ├── flash_rt_kernels-d0db114-...-py310.so    # Python ext (top level)
│       ├── flash_rt_fa2-d0db114-...-py310.so        # Python ext (top level)
│       └── substrate/                                # subdir: validator skips, loader finds
│           ├── libflashrt_exec-d0db114-sm120-cu130-linux-x86_64.so
│           ├── libflashrt_cpp_pi05_c-d0db114-sm120-cu130-linux-x86_64.so
│           ├── libcapsule_nexus_flashrt-frd0db114.nx8f13a3a-sm120-cu130-linux-x86_64.so
│           ├── nexus_python/                         # vendored Nexus serve package
│           └── VERSION                               # ABI fingerprint (single source of truth)
├── run.py                             # RunEngine: single-shot predict
├── serve.py                           # ServeEngine: stateful HTTP serve
├── _substrate_loader.py               # ctypes loader for the 3 C libs + ABI checks
├── _pi05_infer.py / _pi05_compat.py   # Pi0.5 helpers (image load, FP8 shim)
├── build.sh / _bundle_build.sh        # build pipeline
├── pack.sh / release.sh               # pack + FlashHub release
└── release-matrix.env                 # release matrix definition
```

## Why a separate bundle?

`pi05_libero` is a single-shot script for smoke tests and benchmarks. This bundle is the **production** form: long-running, stateful, episode-aware, suitable for robot control loops. Keeping them separate avoids breaking existing `pi05_libero` users.

## Substrate ABI fingerprint

`runtime/<env_key>/substrate/VERSION` records the exact FlashRT + Nexus commits this bundle was built against. Loading is fail-fast: if the bundled `libcapsule_nexus_flashrt.so` does not link the bundled `libflashrt_exec.so` (e.g. someone replaced one without the other), `_substrate_loader` raises at startup.

## Build / release

Maintainer docs: [`BUILD.md`](BUILD.md) / [`BUILD.zh-CN.md`](BUILD.zh-CN.md).

