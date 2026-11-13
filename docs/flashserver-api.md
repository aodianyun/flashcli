# flashserver: HTTP API

<p align="right"><strong>English</strong> · <a href="flashserver-api.zh-CN.md">简体中文</a></p>

The daemon serves a local HTTP API on `127.0.0.1:8790` (the installer may choose
another port on Windows — read `%LOCALAPPDATA%\FlashServer\api-url.txt`).
[openapi.yaml](openapi.yaml) is the **authoritative** contract and is also served
at `/openapi.yaml`; an HTML reference is at `/docs`.

Authentication is off by default. With a token, every path except `/health`, `/`,
`/docs`, `/ui/*`, and `/openapi.yaml` requires `Authorization: Bearer <token>` or
`X-Flashcli-Token`.

## Endpoint index

| Group | Endpoints | Notes |
|---|---|---|
| Health / version | `GET /health`, `GET /v1/version` | `health` is unauthenticated |
| Models | `GET /v1/models`, `GET /v1/models/loaded`, `POST /v1/models/load`, `POST /v1/models/unload`, `POST /v1/models/smoke`, `POST /v1/models/clean` | Schema in [openapi.yaml](openapi.yaml) |
| Model options | `GET/PUT/DELETE /v1/models/options` | `serve_options` + saved host/port, see [flashserver-desktop.md](flashserver-desktop.md#startup-parameters-and-lan-access) |
| Jobs | `POST /v1/pull`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/events`, `POST /v1/jobs/{id}/cancel` | Async work; progress also streams over `/v1/ws` |
| System | `GET /v1/system`, `GET /v1/gpu`, `GET /v1/gpu/history`, `GET /v1/resources`, `GET /v1/storage` | Telemetry and capacity |
| Logs | `GET /v1/logs`, `GET /v1/logs/download` | `?kind=server\|model&ref=…&lines=N` |
| Catalog | `GET /v1/catalog`, `GET /v1/catalog/tags`, `GET /v1/catalog/{id}` | FlashHub proxy |
| Mirror | `GET /v1/mirror`, `POST /v1/mirror` | Domestic mirrors for new downloads |
| Live / UI | `GET /v1/ws`, `GET /`, `GET /docs`, `GET /openapi.yaml`, `POST /v1/ui/chat` | WebSocket state; embedded console |

## Examples

```bash
# load a bundle, then call the endpoint it returns
curl -H 'Content-Type: application/json' \
  -d '{"ref":"flashcli-bundle/qwen3_8b_nvfp4:1.0.0"}' \
  http://127.0.0.1:8790/v1/models/load

curl http://127.0.0.1:18100/v1/chat/completions ...
```

- `load` requires a `serve` entry: run-only bundles are rejected with
  `bundle "..." is run-only (no serve entry)` — use `flashcli run` instead.
- There is no `/v1/infer`; call the returned `endpoint` directly.
- `POST /v1/models/smoke` runs `flashcli run` at low priority for run-only
  bundles, or one `ping` chat request for a started serve model; progress streams
  over `/v1/ws` and is appended to `<ref>.smoke.log`.
- When `addr` is bound to `0.0.0.0`, other devices on the LAN can reach the API
  without a token unless one is configured.

## Cleanup semantics

- **Shared cache** (`~/.flashcli/cache`, `python`, `tools`) —
  `POST /v1/storage/clean {"targets":["cache"]}` (CLI: `flashcli cache clean`).
- **Model data** (bundle, per-bundle runtime, weights) —
  `POST /v1/models/clean {"refs":[...]}` (CLI: `flashcli bundle clean`). Shared
  weights/runtime are kept while another cached ref references them; both calls
  return freed bytes.

Disk accounting and cleanup paths come from the shared `host` layer, so the CLI
and the API always agree. Idempotency, error codes, and payloads are specified in
[openapi.yaml](openapi.yaml).
