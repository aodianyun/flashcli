# flashserver: HTTP API

<p align="right"><strong>English</strong> · <a href="flashserver-api.zh-CN.md">简体中文</a></p>

The daemon serves a local HTTP API on `127.0.0.1:8790` (the installer may choose
another port on Windows — read `%LOCALAPPDATA%\flashcli-desktop\api-url.txt`).
Two namespaces share the port:

- `/v1/*` — **OpenAI-compatible gateway**. Applications and the desktop use it
  for inference only. They never start, stop, load, unload, or receive child
  serve endpoints.
- `/api/v1/*` — **management API**: cached models, disk preload/unload, jobs,
  applications, telemetry, logs, and the management WebSocket.

[openapi.yaml](openapi.yaml) is the **authoritative** contract and is also served
at `/openapi.yaml`; an HTML reference is at `/docs`. Gateway and scheduler
behavior is specified in
[flashserver_gateway_scheduler_spec.md](flashserver_gateway_scheduler_spec.md).

Authentication is off by default. With a token, every path except `/health`, `/`,
`/docs`, `/ui/*`, and `/openapi.yaml` requires `Authorization: Bearer <token>` or
`X-Flashcli-Token`.

## Gateway (`/v1`)

| Endpoints | Notes |
|---|---|
| `GET /v1/models` | OpenAI list of locally available (preloaded or resident) bundle refs |
| `POST /v1/chat/completions`, `/completions`, `/responses`, `/embeddings`, `/moderations` | Mounted when the requested bundle declares the capability |
| `POST /v1/audio/*`, `/images/*`, `/videos`, `/messages`, `/messages/count_tokens` | Capability-gated |
| `WS /v1/realtime` | Capability-gated realtime session |

- `model` must be a **full bundle ref** (`flashcli-bundle/<name>:<version>`).
  Short names, aliases, and latest-version lookup are not supported.
- The scheduler preloads missing assets and starts/stops residents internally.
  While a model is preparing or starting, the gateway returns `503` with
  `Retry-After` instead of blocking the first request. An absent model starts a
  background preload and returns `503 model_preparing` plus
  `X-Flashcli-Preload-Job`; a starting resident returns `503 model_starting`
  with `Retry-After: 2`.
- `503 no_placement` and `429 queue_full` report scheduling failures; the
  response `model` field is rewritten to the requested full ref, and child
  serve endpoints are never exposed.
- Unsupported routes for a model's capabilities return an explicit error; they
  are never forwarded blindly.

## Management (`/api/v1`)

| Group | Endpoints | Notes |
|---|---|---|
| Health / version | `GET /health`, `GET /api/v1/version` | `health` is unauthenticated |
| Models | `GET /api/v1/models`, `GET /api/v1/models/loaded`, `POST /api/v1/models/preload`, `POST /api/v1/models/load`, `POST /api/v1/models/unload`, `POST /api/v1/models/smoke`, `POST /api/v1/models/clean` | Schema in [openapi.yaml](openapi.yaml) |
| Model options | `GET/PUT/DELETE /api/v1/models/options` | `serve_options` + saved host/port, see [flashserver-desktop.md](flashserver-desktop.md#startup-parameters-and-lan-access) |
| Jobs | `POST /api/v1/pull`, `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/events`, `POST /api/v1/jobs/{id}/cancel` | Async work; progress also streams over `/api/v1/ws` |
| System | `GET /api/v1/system`, `GET /api/v1/gpu`, `GET /api/v1/gpu/history`, `GET /api/v1/resources`, `GET /api/v1/devices`, `GET /api/v1/scheduler`, `GET /api/v1/storage` | Telemetry, device inventory, and placement answers |
| Logs | `GET /api/v1/logs`, `GET /api/v1/logs/download` | `?kind=server\|model&ref=…&lines=N` |
| Catalog | `GET /api/v1/catalog`, `GET /api/v1/catalog/tags`, `GET /api/v1/catalog/{id}` | FlashHub proxy |
| Mirror | `GET /api/v1/mirror`, `POST /api/v1/mirror` | Domestic mirrors for new downloads |
| Apps | `GET/POST/DELETE /api/v1/apps/*` | Install/prepare apps; inference always goes through `/v1` |
| Live / UI | `GET /api/v1/ws`, `GET /`, `GET /docs`, `GET /openapi.yaml`, `POST /api/v1/ui/chat` | WebSocket state; embedded console |

Model objects in `GET /api/v1/models` and `GET /api/v1/models/loaded` include a
`capabilities` array. `null` means the host does not own routes for that serve
entry (script/native or unknown); `[]` means host inference routes are disabled.

## Devices and placement

- `GET /api/v1/devices` returns the WSL-visible inventory: NVIDIA dGPUs
  (`nvidia-smi`), the CPU, RAM, and cgroup limits. iGPU/AMD/Windows-native
  devices are out of scope.
- `GET /api/v1/scheduler` returns resident models, slot counts,
  queue/reservations, and one `ResourceRequirement` per cached serve bundle:
  which GPU runtime cells match, which devices satisfy `gpu_count` and
  `min_vram_mib + vram_headroom_mib`, whether a CPU runtime exists, and the
  no-placement reason (`no_compatible_runtime` / `resource_exhausted`).
- Placement is host-only. Bundles declare `min_vram_mib`, optional `gpu_count`,
  and optional `min_ram_mib`; they never select devices.
- CPU is a candidate only when no compatible GPU runtime exists, never because
  VRAM is temporarily short.

## Cached model lifecycle

- `POST /api/v1/models/preload` downloads the bundle and weights and prepares
  the runtime/venv without starting a serve process. It is idempotent and
  returns a job while running.
- `POST /api/v1/pull` is the legacy low-level download job; `preload` is the
  gateway-facing disk operation.
- `POST /api/v1/models/load` starts a resident serve process for the model page.
- `POST /api/v1/models/unload` stops the resident process and deletes bundle,
  weights, runtime, and cache records. It returns `409 model_busy` while the
  model is resident or has active requests; `wait_seconds` waits and `force`
  stops it first. Shared bundle/weights/runtime are kept while another cached
  ref references them.
- `POST /api/v1/models/clean` is the multi-ref cleanup variant; resident models
  are skipped.

The gateway contract adds scheduler-owned resident start/stop on top of these
disk primitives; see
[flashserver_gateway_scheduler_spec.md](flashserver_gateway_scheduler_spec.md).

## Examples

```bash
# preload disk assets without starting the model
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/api/v1/models/preload

# inference through the gateway (the scheduler starts the resident)
curl -H 'Content-Type: application/json' \
  -d '{"model":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0",
       "messages":[{"role":"user","content":"Hello"}]}' \
  http://127.0.0.1:8790/v1/chat/completions
```

- `POST /api/v1/models/load` starts a resident model explicitly for the model
  page and requires a `serve` entry: run-only bundles are rejected with
  `bundle "..." is run-only (no serve entry)` — use `flashcli run` instead.
- `POST /api/v1/models/smoke` runs `flashcli run` at low priority for run-only
  bundles, or one capability-appropriate `ping` request for a started serve
  model; modality-only models without a declarable route report an explicit
  error. Progress streams over `/api/v1/ws` and is appended to
  `<ref>.smoke.log`.
- When `addr` is bound to `0.0.0.0`, other devices on the LAN can reach the API
  without a token unless one is configured.

## Cleanup semantics

- **Shared cache** (`~/.flashcli/cache`, `python`, `tools`) —
  `POST /api/v1/storage/clean {"targets":["cache"]}` (CLI: `flashcli cache clean`).
- **Model data** (bundle, per-bundle runtime, weights) —
  `POST /api/v1/models/clean {"refs":[...]}` (CLI: `flashcli bundle clean`). Shared
  weights/runtime are kept while another cached ref references them; both calls
  return freed bytes.

Disk accounting and cleanup paths come from the shared `host` layer, so the CLI
and the API always agree. Idempotency, error codes, and payloads are specified in
[openapi.yaml](openapi.yaml).
