# flashserver gateway and scheduler development plan

<p align="right"><strong>English</strong> · <a href="flashserver_gateway_scheduler_plan.zh-CN.md">简体中文</a></p>

The contract is [flashserver_gateway_scheduler_spec.md](flashserver_gateway_scheduler_spec.md). This
document is the execution plan; the spec wins on every behavior question.

## 1. Goal

Move from “load returns a child endpoint” to:

- applications and the desktop call only the OpenAI gateway at `/v1/*`;
- flashserver owns preload, placement, resident start/stop, leases, eviction, and
  unload;
- management/control APIs live under `/api/v1/*`;
- applications cannot start, stop, load, unload, or select devices;
- preload/remove are disk operations; resident start/stop are internal.

No backward compatibility is required. The desktop is the only client and is
updated in the same release.

## 2. Workstreams

### M0 — contract and route split

Deliverables:

- this plan + the authoritative spec (English + zh-CN mirror), indexed.
- `/v1/*` reserved for the gateway; all management routes moved to
  `/api/v1/*` on the same port.
- `/health`, `/`, `/ui/*`, `/docs`, `/openapi.yaml` remain outside both
  namespaces.
- desktop management base switched to `/api/v1`; management WebSocket to
  `/api/v1/ws`.
- OpenAPI split/updated for both namespaces.
- AGENTS/CONTRIBUTING reference the spec as mandatory.

Exit criteria:

- no management route remains under `/v1/*`;
- desktop can list models/resources/logs through `/api/v1`;
- existing non-gateway tests migrated to the new paths;
- docs links and zh mirror pass.

### M1 — disk state, preload, unload

Deliverables:

- persistent per-ref preload state: `absent`, `preloading`, `preloaded`,
  `unloading`.
- `preload` job wrapper over `host.Pull` with dedupe, progress, cancel, resume.
- `unload` job wrapper over `host.RemoveCachedRef`:
  - busy/lease checks, `wait_seconds`, `force`;
  - stop resident before deletion;
  - shared bundle/weights/runtime retained;
  - preload state removed.
- `/api/v1/models/preload`, `/api/v1/models/unload`,
  `/api/v1/models` state output.
- no serve process or VRAM reservation in preload.

Tests:

- idempotent preload; concurrent preload dedupe; failed/resumed download.
- unload when busy: 409, wait, timeout, force.
- shared assets kept; exclusive assets removed.
- daemon restart preserves preload state and jobs behave safely.

Exit criteria:

- an absent model can be prepared with no child process;
- unload never deletes assets while resident/busy unless `force`;
- state survives restart.

### M2 — device inventory and resource accounting

Deliverables:

- device inventory for WSL: NVIDIA dGPUs (`nvidia-smi`), CPU, RAM, cgroup
  limits.
- runtime-cell compatibility mapping (which runtime can run on which device).
- VRAM/RAM/CPU reservations with `vram_headroom_mib`.
- `/api/v1/devices` and `/api/v1/scheduler`.
- resource fields in manifest: `min_vram_mib` (GPU), optional `gpu_count`,
  optional `min_ram_mib` (CPU).
- validation: GPU runtime requires `min_vram_mib`; `gpu_count >= 1`; no
  placement/device fields in bundles.

Tests:

- fake multi-GPU inventory; per-GPU free memory; all-or-nothing `gpu_count`
  reservation.
- CPU/RAM accounting and WSL memory cap.
- unsupported/absent runtime cell produces `no_compatible_runtime`.
- invalid resource fields fail `bundle validate`.

Exit criteria:

- scheduler can answer “can this ref run here, on which devices?” without
  starting a process;
- no model-specific resource logic in Go.

### M3 — scheduler: resident lifecycle

Deliverables:

- `LoadScheduled(ref)` distinct from admin preload; does not persist/pin.
- resident state machine: stopped/starting/ready/busy/stopping.
- lease increment/release; no eviction/unload with active leases.
- `max_loaded`, LRU idle stop, `idle_stop_seconds`, `queue_*`.
- placement selection, eviction, VRAM release wait, retry.
- CPU fallback only when no compatible GPU runtime exists.
- `/api/v1/models` resident fields, `/api/v1/scheduler` queue/reservations.

Tests:

- two requests share one load; loading dedupe.
- LRU evicts idle, never busy.
- max_loaded and VRAM admission; headroom.
- multi-GPU reservation; CPU fallback rules.
- queue timeout/429 and resource_exhausted 503.
- idle stop keeps `preloaded`; next request starts again.
- crash/OOM recovery reloads once, no loop.

Exit criteria:

- no app-facing start/stop API;
- resident lifecycle is fully scheduler-owned;
- all admission/eviction decisions tested with fake devices.

### M4 — gateway core

Deliverables:

- `/v1/models` OpenAI list for preloaded/resident refs.
- JSON routes: chat, completions, responses, embeddings, moderations.
- full-ref `model` validation; capability gate.
- auto-pull: background job + `503 model_preparing` + `Retry-After` +
  `X-Flashcli-Preload-Job`.
- auto-resident: bounded wait + `503 model_starting` + `Retry-After: 2`.
- reverse proxy: status, headers, body, client cancellation; no child endpoint
  exposure.
- response `model` rewrite to the requested full ref (JSON and SSE).
- OpenAI-shaped errors: `model_not_found`, `model_preparing`,
  `model_starting`, `no_placement`, `resource_exhausted`, `queue_full`,
  `model_busy`.
- Retry-After policy exactly as in the spec.

Tests:

- JSON proxy and error passthrough/normalization.
- SSE flush, chunk order, disconnect cancellation.
- auto-pull 503, retry, success; job dedupe.
- preloaded but stopped -> start; busy -> lease.
- unknown ref 404; unsupported capability 4xx.
- no child endpoint leakage.

Exit criteria:

- a standard OpenAI client can use `http://host:8790/v1` for the JSON/SSE
  routes without knowing bundle internals;
- first request never blocks indefinitely on preload/start.

### M5 — multipart, WebSocket, full protocol

Deliverables:

- audio/images/videos multipart `model` extraction with bounded buffering and
  cancellation.
- WebSocket `/v1/realtime` target selection and proxy.
- Anthropic messages/count_tokens under the same gateway rules.
- capability-specific route errors.
- request/response size limits, timeouts, and streaming backpressure.

Tests:

- multipart without/with `model`; large body; client cancel.
- WebSocket connect/upgrade/bidirectional frames/close.
- mixed capability models reject undeclared routes.
- slow consumer and upstream failure handling.

Exit criteria:

- all declared gateway routes work through one port;
- no per-modality logic in the host; future schemas remain bundle-declared.

### M6 — app and desktop migration

Deliverables:

- app install/prepare only preloads refs; no model start/stop.
- remove app start/stop endpoints and desktop controls.
- setup scripts use `FLASHCLI_API_BASE=http://<host>:8790/v1`.
- AppState no longer treats child `pid`/`endpoint` as an inference target.
- desktop management `/api/v1`, inference `/v1`; show preload/resident/device
  status and disk preload/unload actions only.
- model “use” examples use the gateway.

Tests:

- app install/preload followed by `/v1` inference; no endpoint use.
- desktop route parity tests for `/api/v1`.
- old start/stop calls are absent (404) and not used by the desktop.
- setup-script environment points to the gateway.

Exit criteria:

- no app/desktop code path calls model start/stop or child endpoints;
- only `/v1` is used for inference.

### M7 — hardening and release

Deliverables:

- observability: request logs, preload/resident/evict events, queue/lease metrics.
- security: token shared with gateway, child loopback only, token stripping.
- config validation and defaults.
- WSL dGPU single/multi-card and CPU runtime acceptance.
- OpenAPI, docs, zh mirrors, release notes.
- failure injection: network loss, disk full, GPU OOM, child crash, daemon
  restart.

Exit criteria:

- full acceptance suite green on WSL with a real NVIDIA GPU;
- a prepared model survives daemon restart;
- unload/force behavior verified against a real busy stream;
- docs and spec updated together.

## 3. Test matrix

| Area | Unit | Integration | Acceptance |
|---|---|---|---|
| full ref / route | yes | yes | yes |
| preload/unload | yes | yes | yes |
| active lease / force | yes | yes | yes |
| auto-pull Retry-After | yes | yes | yes |
| resident start / idle stop | yes | yes | yes |
| LRU / max_loaded / VRAM | yes | yes | yes |
| multi-GPU `gpu_count` | yes | fake | WSL real if available |
| CPU fallback rules | yes | fake | WSL CPU runtime if available |
| JSON / SSE / multipart / WS | yes | yes | yes |
| app/desktop no start/stop | static | yes | yes |

## 4. Definition of done

- Apps and desktop use `/api/v1` management and `/v1` inference only.
- Apps cannot start/stop/load/unload models or see child endpoints.
- `preload` prepares disk assets and `unload` deletes them with busy/force
  semantics; automatic eviction only stops residents.
- First inference auto-pulls/preloads and returns standard `503` +
  `Retry-After` while work continues.
- Placement is host-only; bundles declare runtime cells and resource needs only.
- CPU fallback happens only when no compatible GPU runtime exists.
- WSL supports NVIDIA dGPU(s) and CPU runtime; iGPU/Windows native remain out of
  scope.
- Tests and docs (English + zh-CN) are updated in the same change.

## 5. Compliance rules

- The spec is authoritative. A behavior change requires a spec + zh-CN update
  first; code must not diverge.
- Do not add model-specific parameters, shapes, placement hints, or device
  choices to `go/`; use bundle manifest/runtime contracts.
- Do not reintroduce app-facing model start/stop or child endpoints.
- Do not route management APIs under `/v1/*`.
- Every new route/state/config must be covered by tests and OpenAPI/docs.
- `bundle validate` and scheduler admission must agree on resource fields.
