# OCR bundle packaging standard (OpenAI-compatible service + multi-image/batch)

<p align="right"><strong>English</strong> · <a href="bundle_ocr_standard.zh-CN.md">简体中文</a></p>

> **Category supplement.** The generic manifest, layout, weights, runtime and publishing rules remain authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) (zh: [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)). This page adds only OCR-specific requirements.
>
> **Gateway passthrough.** OCR bundles use `format_version: 4`, engine mode, a `ServeEngine`, and `register_routes(app)` for the native `/v1/ocr`, `/v1/ocr/batch` and `/v1/ocr/info` routes. To add the `ocr` extension and OCR-specific streaming semantics, the bundle also registers `/v1/chat/completions` and `/v1/responses`; these overrides take priority over the host defaults and own their parsing/SSE/error shape. Host base routes remain host-owned. The flashserver `/v1` gateway forwards these paths to the model's serve endpoint, so the same base URL exposes both the standard OpenAI routes and the native OCR routes. Custom paths that do not carry `model` in the body use `?model=<full-ref>`; see [bundle_serve_protocols.md](bundle_serve_protocols.md) §1.2.
>
> **Generic rules are not repeated.** Manifest/layout/entry/runtime/weights/publishing are defined in [bundle_publish_standard.md](bundle_publish_standard.md); engine-mode host behavior (standard routes, auth, concurrency, request logging, SSE transport, error translation) is defined in [bundle_serve_protocols.md](bundle_serve_protocols.md). This page adds only OCR-specific routes, schemas, limits, and acceptance.

> Applies to: OCR (text detection + text recognition) models adapted by FlashRT,
> published to FlashHub as a flashcli bundle (`format_version: 4`) and served over
> HTTP by `flashcli serve`.
>
> This page is the **OCR service** supplement to the
> [flashcli Model Bundle publishing standard](bundle_publish_standard.md): the
> generic directory layout, manifest, `.so` naming, weights and provenance
> requirements remain governed by that standard; this page only specifies what an
> OCR bundle must additionally satisfy. It is not the LLM spec; for LLMs use
> [llm_bundle_standard.md](llm_bundle_standard.md).

Reference implementation (already published under this standard and verified in practice):

| Model | FlashHub reference | Notes |
|---|---|---|
| PP-OCRv6 medium det + rec | `aodianyun/paddleocr_v6:1.0.3` | Reference implementation; RTX 3060 / 4060 Ti / 5060 Ti (SM86 / SM89 / SM120) |

The full project-level contract of the reference implementation lives in the FlashRT repository at
`docs/paddleocr_v6_serve.zh-CN.md`; this page extracts the **generic requirements** from it so
that other OCR models can reuse them.

---

## Contents

1. Goals and overall requirements
2. Architecture: the `ocr_serve` protocol layer and model glue
3. Published directory layout
4. Manifest (`flashcli-bundle.json`) rules
5. Glue interface: `ServeEngine` + backend contract
6. Entry points: `serve.py` / `run.py`
7. OCR data model: the `ocr` extension object
8. OpenAI Chat Completions extension
9. OpenAI Responses extension
10. Native `/v1/ocr`
11. Batch multi-output `/v1/ocr/batch`
12. Image input (URL / base64 / local path)
13. Server behavior rules (must be identical everywhere)
14. Endpoint list and call examples
15. Testing and acceptance
16. Packaging, publishing and versioning
17. FAQ
Appendix A. `ocr` object schema
Appendix B. Error codes

---

## 1. Goals and overall requirements

`flashcli serve` for an OCR bundle **must**:

1. Use an **engine-mode** `ServeEngine`; the listen address/port are provided by the host's
   `--host` (default `0.0.0.0`) / `--port` (default `8000`);
2. Provide both the **OpenAI-compatible** (`/v1/chat/completions`, `/v1/responses`)
   and the **native OCR** (`/v1/ocr`) endpoints; the OCR bundle overrides chat/responses for the `ocr` extension and native routes, while host base routes remain host-owned;
3. Support **multi-image input**: one request may carry several images, and per-image
   results are returned in input order;
4. Support **batch JSON multi-output** `/v1/ocr/batch`: one call names several inputs
   (each item may hold several images) plus a per-item output format, and returns
   `results[]` in order;
5. Support all five image input forms — **local path / `file://` / data URL / bare base64 /
   http(s) URL** (local paths may be sandboxed or disabled);
6. Provide a top-level `ocr` extension object beyond the standard response (per image,
   per line text/confidence/polygon);
7. Support SSE streaming (Chat Completions and Responses);
8. Perform **no calibration at startup**: do not load a calibration dataset, do not run a
   calibration forward pass; bundles contain no calibration data;
9. Reuse the shared `ocr_serve/` protocol layer (never modified per model); model
   differences live only in the "glue/backend";
10. Publish only after passing the acceptance in §15.

Usage is identical for every OCR bundle:

```bash
flashcli serve <org>/<name>:<version> --host 0.0.0.0 --port 8080 --api-key <key>
# OpenAI-compatible: base_url = http://<host>:8080/v1
# Native OCR:        POST http://<host>:8080/v1/ocr
# Batch:             POST http://<host>:8080/v1/ocr/batch
```

---

## 2. Architecture: the `ocr_serve` protocol layer and model glue

```text
                 flashcli serve <ref> --host H --port P [--api-key K ...]
                                                │  engine mode: the host builds the FastAPI app and listens
                                                ▼
┌─ ocr_serve/  protocol layer (shared verbatim by all OCR bundles, never modified per model) ──┐
│  server.py      /v1/ocr  /v1/ocr/batch  /v1/ocr/info  OCR FIFO queue, SSE                   │
│                 (host owns base routes/auth; OCR overrides chat/responses, own queue/SSE)   │
│  openai_api.py  parse both OpenAI dialects, shape OCR results, SSE events                    │
│  media.py       data URL / base64 / http(s) / local path parsing, size + SSRF checks         │
│  datatypes.py   framework-independent request/result/error types                             │
└───────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                │  backend contract (§5)
                                                ▼
┌───────────────────────────────────── written per model ──────────────────────────────────────┐
│  ocr_serve/backend.py  load / warmup / run_image / info; graph-capture boundary (model glue) │
│  serve.py              class ServeEngine(ocr_serve.server.OcrServeEngine): pass              │
│  run.py                flashcli run entry (reuses the same backend)                          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Rules:

- The `ocr_serve/` protocol files (`server.py` / `openai_api.py` / `media.py` /
  `datatypes.py` / `__init__.py`) depend only on `fastapi` / `uvicorn` /
  `pydantic` and the standard library — not on torch. They own OCR-specific request
  parsing, result shaping, SSE, batch handling, image validation, and the OCR FIFO
  queue. The bundle overrides chat/responses for the `ocr` extension; the host owns base
  routes, authentication, the concurrency gate, request logging and the error envelope.
- `ocr_serve/backend.py` is the model glue and may depend on runtime libraries such as
  torch/OpenCV; porting to another OCR model means replacing its implementation while
  keeping the interface unchanged.
- The glue does not handle HTTP/JSON/SSE/queueing; the protocol layer knows nothing
  about any specific OCR model.
- When the protocol layer must change, sync the change to every OCR bundle so behavior
  stays identical.

The host-side `ServeEngine` protocol and engine-mode routing are specified in
[bundle_serve_protocols.md](bundle_serve_protocols.md); the entry backend ABI is in
[bundle_execution_abi.md](bundle_execution_abi.md).

---

## 3. Published directory layout

```text
<bundle>/                         # publish root (dist/)
├── flashcli-bundle.json          # manifest (§4)
├── serve.py                      # flashcli serve entry (ServeEngine, engine mode)
├── run.py                        # flashcli run entry (RunEngine, engine mode)
├── ocr_serve/
│   ├── __init__.py  datatypes.py  media.py       # protocol layer, copied verbatim
│   ├── openai_api.py  server.py                  # protocol layer, copied verbatim
│   └── backend.py                                # model glue, replaced per model
├── flash_rt/                     # FlashRT Python sources reachable from entry (no .so)
├── runtime/<env-key>/*.so        # native libraries per environment
└── README.md                     # usage notes and endpoint summary
```

- The published tree must be minimal: this standard document, test scripts, `.gitignore`,
  caches, calibration/test images and weights must not enter `dist/`.
- Do not name modules `types.py` or similar names that collide with the standard library
  (it would shadow stdlib).

---

## 4. OCR-specific manifest settings

The generic manifest schema, entry rules, dependencies and weights are defined in [bundle_publish_standard.md](bundle_publish_standard.md). Only the OCR-specific serve options and resource requirements are listed here.

- `entry.serve.capabilities` MUST include `openai.chat` and `openai.responses` so the gateway routes the overridden chat/responses paths. No separate OCR capability is required; `/v1/ocr*` are custom paths.

### 4.3 Shared serve_options (required in every OCR bundle, identical names and semantics)

```json
[
  {"name": "model_name", "type": "string", "default": "<ocr-model>", "phase": "load",
   "help": "Model id reported in responses (requests may name any model)."},
  {"name": "api_key", "type": "string", "default": "", "phase": "load",
   "help": "Require this key on /v1/* as 'Authorization: Bearer <key>' or 'x-api-key: <key>'."},
  {"name": "device", "type": "string", "default": "cuda", "phase": "load",
   "help": "CUDA device string."},
  {"name": "max_queue", "type": "integer", "default": 32, "phase": "load",
   "help": "Requests allowed to wait for the single GPU slot (FIFO); beyond it 503 (0 = unlimited)."},
  {"name": "max_wait_sec", "type": "float", "default": 60.0, "phase": "load",
   "help": "Longest time a request may wait for the GPU slot before 503 (0 = forever)."},
  {"name": "max_images", "type": "integer", "default": 8, "phase": "load",
   "help": "Maximum images per request (or per batch item)."},
  {"name": "max_batch", "type": "integer", "default": 32, "phase": "load",
   "help": "Maximum items in one /v1/ocr/batch call."},
  {"name": "max_image_bytes", "type": "integer", "default": 20971520, "phase": "load",
   "help": "Maximum decoded image size in bytes (default 20 MiB)."},
  {"name": "image_url_timeout_sec", "type": "float", "default": 15.0, "phase": "load",
   "help": "Timeout for downloading an http(s) image URL."},
  {"name": "image_url_ports", "type": "string", "default": "80,443", "phase": "load",
   "help": "Comma-separated ports allowed in http(s) image URLs (empty: any port)."},
  {"name": "allow_private_image_urls", "type": "boolean", "default": false, "phase": "load",
   "help": "Allow image URLs resolving to loopback/private/link-local addresses (SSRF guard)."},
  {"name": "allow_local_image_paths", "type": "boolean", "default": true, "phase": "load",
   "help": "Accept local image paths and file:// URLs and read the file directly."},
  {"name": "local_image_root", "type": "string", "default": "", "phase": "load",
   "help": "If set, local paths must resolve inside this directory (empty: any readable path)."},
  {"name": "warmup", "type": "string", "default": "", "phase": "warmup",
   "help": "Comma-separated image paths to pre-capture graphs before serving."}
]
```

- Model-specific parameters (thresholds, input size limits, graph-capture limits, etc.)
  follow after these and are read by `load(**options)`.
- `warmup` has phase=`warmup`; the host calls `ServeEngine.warmup(spec)` after loading.
- `run_options` are declared per the publishing standard (`image`, `output`, `json_output`,
  `device`, etc.).

## 5. Glue interface: `ServeEngine` + backend contract

### 5.1 `ServeEngine`

`serve.py` subclasses the protocol-layer base class; `OcrServeEngine.__init__` creates
`ocr_serve.backend.OcrBackend`, so porting another model only requires replacing the
implementation of `ocr_serve/backend.py` — `serve.py` stays at three lines:

```python
"""flashcli serve entry (engine mode) for <model>."""
from __future__ import annotations

from ocr_serve.server import OcrServeEngine


class ServeEngine(OcrServeEngine):
    """<model> det+rec behind the flashcli serve HTTP surface."""
```

`OcrServeEngine` already implements:

- `model_id` / `load` / `warmup` / `chat` / `chat_stream` (the flashcli
  `ServeEngine` protocol);
- `register_routes(app)`: auth, logging, FIFO queue and all HTTP routes;
- request parsing, result shaping, SSE, batching and error handling.

### 5.2 Backend contract

Each model implements one backend class (`backend.py`):

```python
class Backend:
    device: str = "cuda"
    precision: str = "fp16"

    def load(self, checkpoint: str | Path, options: dict) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def run_image(self, data: bytes) -> ImageResult: ...
    def info(self) -> dict: ...
```

- `load`: load once and keep resident in VRAM; read the checkpoint passed by the manifest.
- `warmup`: pre-capture/warm up using the comma-separated image paths; an empty value does
  nothing.
- `run_image`: decode one image and run the full OCR pipeline, returning
  `ImageResult(width, height, rec_texts, rec_scores, rec_polys, det_scores, e2e_ms, image_bytes)`.
- `info`: runtime status for `/v1/ocr/info` (device, GPU, capture state, etc.).
- The backend must serialize GPU calls itself (the protocol layer already guarantees a
  single slot, but the synchronous `chat()` path may also be called by the host).
- **Do not** load calibration data or run a calibration forward pass in `load`/`warmup`.

Reference implementation: `ocr_serve/backend.py` of `paddleocr_v6`.

---

## 6. Entry points

The host loads `ServeEngine` / `RunEngine` according to [bundle_serve_protocols.md](bundle_serve_protocols.md); OCR bundles must not start their own HTTP server. The `ocr_serve` protocol layer is mounted through `ServeEngine.register_routes`.

## 7. OCR data model: the `ocr` extension object

Every OpenAI response adds a top-level `ocr` on top of the standard fields:

```json
{
  "object": "ocr.result",
  "version": 1,
  "engine": "<engine-id>",
  "model": "<model-id>",
  "device": "cuda",
  "precision": "fp16",
  "image_count": 1,
  "line_count": 2,
  "text": "First line\nSecond line",
  "e2e_ms": 15.23,
  "images": [
    {
      "index": 0,
      "width": 896,
      "height": 528,
      "text": "First line\nSecond line",
      "line_count": 2,
      "lines": [
        {"text": "First line", "score": 0.9987, "polygon": [[12, 30], [220, 30], [220, 62], [12, 62]]},
        {"text": "Second line", "score": 0.9971, "polygon": [[12, 70], [300, 70], [300, 102], [12, 102]]}
      ],
      "det_scores": [0.987, 0.981],
      "e2e_ms": 15.23,
      "image_bytes": 123456
    }
  ]
}
```

Fields, semantics and request-level options (`format` / `line_separator` /
`include_polygons` / `include_scores` / `include_det_scores`) are defined in Appendix A.
With `format=json` the assistant content is the JSON string of that object; with
`format=text` the content is the line-by-line text.

---

## 8. OpenAI Chat Completions extension

`POST /v1/chat/completions`

- Image content parts: `image_url` and `input_image`; `image_url` may be
  `{"url": "..."}` or a bare string.
- One message may contain several images; images from several messages are merged in
  order of appearance.
- At least one image is required; otherwise 400 `image_required`.
- `stream: true` is supported; text format streams line by line, JSON format is sent in
  one piece.
- The final streaming chunk carries `finish_reason: "stop"`, `usage` and the complete
  `ocr`.
- `response_format: {"type": "json_object"}` is equivalent to `ocr.format=json`.
- `max_tokens` / `temperature` / `top_p` / `stop` etc. have no effect (OCR generates no
  tokens); `n>1`, `tools` / `functions`, and unknown part types return 400.

Response examples are in §14.

---

## 9. OpenAI Responses extension

`POST /v1/responses`

- `input` is a string or an item list; items support `message` / `input_text` /
  `input_image`; content parts accept the `text` / `image_url` aliases.
- At least one `input_image` is required; otherwise 400.
- `previous_response_id`, `tools`, `function_call` / `function_call_output` /
  `reasoning` items are not supported.
- Non-streaming returns `object: "response"`, `output[]`, `output_text`, `usage`,
  `ocr`.
- Streaming events: `response.created`, `response.in_progress`,
  `response.output_item.added`, `response.content_part.added`,
  `response.output_text.delta`, `response.output_text.done`,
  `response.content_part.done`, `response.output_item.done`,
  `response.completed` (carrying `usage` and `ocr`).

`usage` must include `input_tokens_details.cached_tokens` /
`cache_write_tokens` and `output_tokens_details.reasoning_tokens`, otherwise the official
OpenAI SDK fails to parse it.

---

## 10. Native `/v1/ocr`

`POST /v1/ocr`

```json
{
  "model": "<model-id>",
  "images": [
    "https://example.com/page.jpg",
    "/data/pages/page-1.png",
    "file:///data/pages/page-2.png",
    {"path": "/data/pages/page-3.png"},
    "data:image/png;base64,..."
  ],
  "line_separator": "\n",
  "include_polygons": true,
  "include_scores": true,
  "include_det_scores": true
}
```

- `image` and `images` may appear together; `images` comes first, `image` after it.
- `images[]` elements may be strings or objects (`url` / `path` / `file` /
  `file_url` / `data_url` / `base64` / `image_url` / `data`).
- The response is `ocr.result`, with an additional `created`.
- No streaming.

---

## 11. Batch multi-output `/v1/ocr/batch`

One JSON call names several inputs, each with its own `id`, images and output format:

```json
{
  "continue_on_error": true,
  "requests": [
    {"id": "page-1", "image": "/data/pages/1.png", "format": "json"},
    {"id": "page-2", "images": ["https://example.com/2.jpg", "/data/pages/2b.png"],
     "format": "text", "include_polygons": false}
  ]
}
```

- `requests` may also be written as `inputs` / `items`.
- Each item supports `image` / `images`, `format` (text/json), and an `ocr` options
  object; top-level `format` / `line_separator` / `include_*` provide defaults.
- The response is HTTP 200 with `object: "ocr.batch"`; `results[]` corresponds
  one-to-one with the input order:

```json
{
  "object": "ocr.batch",
  "batch_size": 2,
  "succeeded": 2, "failed": 0, "skipped": 0,
  "e2e_ms": 40.1,
  "results": [
    {"index": 0, "id": "page-1", "status": "ok", "format": "json",
     "content": "{...}", "ocr": {"...": "..."}, "e2e_ms": 18.2},
    {"index": 1, "id": "page-2", "status": "ok", "format": "text",
     "content": "First line\nSecond line", "ocr": {"...": "..."}, "e2e_ms": 21.9}
  ]
}
```

- `continue_on_error=true` (default): a failed item does not affect later items; the
  failed item gets `status: "error"` + `error`;
- `continue_on_error=false`: after the first failure the remaining items get
  `status: "skipped"`;
- a duplicate `id` counts as an error for that item;
- the whole batch occupies a single GPU slot; items run serially.

---

## 12. Image input (URL / base64 / local path)

Supported:

1. Data URL: `data:image/png;base64,....`;
2. Bare base64 (standard or URL-safe);
3. `http://` / `https://` URLs;
4. Local paths: `/abs/path.png`, prefixes `./` / `../` / `~/`, and relative paths
   carrying an image extension (`images/page.jpg`);
5. `file://` URLs (empty host or `localhost`).

Rules:

- `max_image_bytes` applies to the decoded byte size;
- URL: ports 80/443 by default, private/loopback rejected, every redirect hop validated,
  at most 4 hops, timeout `image_url_timeout_sec`;
- local paths: `allow_local_image_paths` (default true); when `local_image_root` is
  non-empty, the `resolve()`d path must lie inside that directory; relative paths are
  relative to the root when one is set, otherwise relative to the process cwd;
- local file missing / not a regular file -> 400 `image_not_found`; non-image content ->
  400 `unsupported_image_type`;
- by default local paths let the process read any readable file; public/multi-tenant
  deployments must set `local_image_root` or disable local paths;
- JPEG / PNG / WebP / BMP / TIFF / GIF are supported; a decode failure returns 400.

---

## 13. Server behavior rules (must be identical everywhere)

> Host base behavior (base routes, authentication, the concurrency gate, request logging and the error envelope) is defined in [bundle_serve_protocols.md](bundle_serve_protocols.md) and is not repeated here. The OCR bundle overrides chat/responses for the `ocr` extension; the rules below are OCR-specific media/queue behavior.

| Rule | Reason / rationale |
| --- | --- |
| OpenAI Chat Completions + Responses + native OCR | Clients reuse the OpenAI SDK directly; the native endpoints serve batch processing |
| `model` in a request may be any value | Clients often hardcode a model name |
| Single GPU, single slot, batch=1 FIFO; 503 only beyond `max_queue` | OCR forward passes occupy the GPU exclusively |
| No calibration at startup; no calibration data in the bundle | Avoids startup cost and data leakage |
| Image URLs to private/loopback are rejected by default; local paths can be sandboxed | SSRF / arbitrary file read protection |
| Multi-image results follow input order, content joined with blank lines | Predictable multi-image semantics |
| Batch isolates per-item errors (default) | One bad image does not fail the whole batch |
| Streaming text is incremental per line; concatenation is byte-identical to non-streaming | Clients can consume as they receive |
| Batch item errors do not change the HTTP status | Uniform client handling |
| Stop sending after the client disconnects; the current frame is not interrupted | OCR is single-frame grained; a kernel cannot be killed safely |

---

## 14. Endpoint list and call examples

| Method | Path | Spec | Notes |
|---|---|---|---|
| POST | `/v1/chat/completions` | OpenAI | Image parts, streaming, `ocr` extension |
| POST | `/v1/responses` | OpenAI | `input_image`, streaming events, `ocr` extension |
| POST | `/v1/ocr` | Native | Single/multi-image structured results |
| POST | `/v1/ocr/batch` | Native | JSON batch multi-output |
| GET | `/v1/ocr/info` | Native | Capabilities, limits, runtime status |

```bash
# Chat Completions (local path)
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"model":"<model>","messages":[{"role":"user","content":[
        {"type":"image_url","image_url":"/data/pages/page.png"}]}],
      "ocr":{"format":"json"}}' | jq .

# Multi-image + batch multi-output
curl -s http://127.0.0.1:8080/v1/ocr/batch \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"requests":[
        {"id":"a","image":"/data/pages/a.png","format":"json"},
        {"id":"b","images":["/data/pages/b1.png","/data/pages/b2.png"],"format":"text"}]}' | jq .
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="<key>")
r = client.chat.completions.create(
    model="<model>",
    messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": "/data/pages/page.png"}]}],
    extra_body={"ocr": {"format": "json"}},
)
print(r.model_extra["ocr"]["images"][0]["lines"])
```

---

## 15. Testing and acceptance

All of the following must be completed before publishing:

| Step | Content | Acceptance |
| --- | --- | --- |
| 1 | `flashcli bundle validate <dist>` | `[ok]` |
| 2 | `flashcli run <dist>` | Text/scores/polygons match the optimization receipt |
| 3 | `flashcli serve <dist>` (target GPU matrix) | Starts successfully and `/v1/ocr/info` responds |
| 4 | Chat Completions non-streaming/streaming | content is byte-identical; `ocr` is complete |
| 5 | Responses non-streaming/streaming | `response.completed` + `ocr`; parseable by the official SDK |
| 6 | `/v1/ocr` single/multi image | `image_count`, order and per-image text are correct |
| 7 | `/v1/ocr/batch` | Order/id/format correct; per-item failure isolation; `skipped` semantics |
| 8 | Local paths | Absolute/relative/`file://` succeed; 400 outside the root and when disabled |
| 9 | Errors and limits | No image, oversized image, private URL, tools, n>1, bad JSON |
| 10 | Concurrency/queueing | Single slot serializes; 503 beyond the queue |
| 11 | Accuracy | Line-by-line identical to `flashcli run` / the optimization receipt |
| 12 | Package contents | No weights, no calibration data, no test images/caches; `.so` is the required minimal set |
| 13 | Cleanup | Runtime caches, logs and `__pycache__` do not enter the package |

Tests must run the `dist/` publish tree through `flashcli serve`, not the development
directory. Remote debugging processes must hold the shared debug lock (for example
`/debuglock/rsi.lock`) so they do not occupy the GPU at the same time as other jobs.

---

## 16. Packaging and publishing

Follow [bundle_publish_standard.md](bundle_publish_standard.md) for the publish tree, manifest, `.so` layout, weights, provenance and FlashHub upload. The OCR-specific acceptance checklist is §15.

## 17. FAQ

| Symptom | Cause / handling |
| --- | --- |
| `flashcli serve --ip ...` reports a parameter error | Engine mode uses `--host`; `ip`/`port` must not be declared in serve_options |
| Client gets 422, routes do not take effect | FastAPI types such as `Request` must be imported at module level (with `from __future__ import annotations`, a local import is treated as a query parameter) |
| OpenAI SDK fails to parse Responses | `usage` lacks `input_tokens_details` / `output_tokens_details`, or lacks `parallel_tool_calls` / `tool_choice` / `tools` |
| Streaming content differs from non-streaming | `content_deltas` must be split by `line_separator` and concatenated back verbatim; do not split JSON format by line |
| Multi-image order is wrong | Collect images in message/array appearance order; do not sort by role or dict keys |
| Local path returns 403/400 | Check `allow_local_image_paths`, `local_image_root`, whether the file exists, and whether it is inside the root after `resolve()` |
| The first request is slow | A new frame size / recognition width captures a graph; pre-capture with `--warmup` |
| VRAM grows with image size | The capture set grows per frame shape/recognition width; set `max_rec_widths`, or group batches by size |
| A public server can read any file | Local paths are allowed by default; you must set `local_image_root` or disable local paths |

---

## Appendix A. `ocr` object schema

```json
{
  "object": "ocr.result",
  "version": 1,
  "engine": "string",
  "model": "string",
  "device": "cuda",
  "precision": "fp16",
  "image_count": 1,
  "line_count": 2,
  "text": "string",
  "e2e_ms": 15.23,
  "images": [{
    "index": 0,
    "width": 896,
    "height": 528,
    "text": "string",
    "line_count": 2,
    "lines": [{
      "text": "string",
      "score": 0.9987,
      "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]
    }],
    "det_scores": [0.987],
    "e2e_ms": 15.23,
    "image_bytes": 123456
  }]
}
```

Request-level OCR options:

| Option | Type / default | Description |
| --- | --- | --- |
| `format` | `text` / `text` | `text`: content is plain text; `json`: content is the JSON string of the `ocr` object |
| `line_separator` | string / `\n` | Line separator; non-empty, ≤ 8 characters |
| `include_polygons` | boolean / `true` | Include `polygon` in `lines[]` |
| `include_scores` | boolean / `true` | Include the recognition `score` |
| `include_det_scores` | boolean / `true` | Include `det_scores` |

Unknown `ocr` keys return 400 (so typos never fail silently).

## Appendix B. Error codes

| HTTP | `code` | Scenario |
| --- | --- | --- |
| 400 | `image_required` | No image |
| 400 | `invalid_image` | Invalid or undecodable base64/data URL |
| 400 | `invalid_image_source` | Invalid `file:` URL / path form |
| 400 | `local_image_paths_disabled` | Local path reading is disabled on this server |
| 400 | `local_image_outside_root` | Local path is not inside `local_image_root` |
| 400 | `image_not_found` | Local file missing/unreadable/not a regular file |
| 400 | `invalid_image_url` | Not http(s), contains credentials, port not allowed, unresolvable |
| 400 | `private_image_url` | URL points to a private/loopback address (allow_private not enabled) |
| 400 | `unsupported_image_type` | Non-image content type |
| 400 | `image_fetch_failed` | Download failed/timed out |
| 400 | `invalid_json` | Request body is not a JSON object |
| 400 | `unsupported_parameter` | `n`, `tools`, `response_format`, unknown part, etc. |
| 400 | `too_many_images` | Exceeds `max_images` |
| 400 | `batch_too_large` | Exceeds `max_batch` |
| 400 | `duplicate_id` | Duplicate batch item id |
| 401 | `invalid_api_key` | API key missing or mismatched |
| 413 | `image_too_large` | Image exceeds `max_image_bytes` |
| 503 | `server_busy` | Queue full or wait timed out |
| 503 | `not_ready` | Model not fully loaded |
| 500 | `internal_error` | Inference/internal exception |

Item errors from the batch endpoint do not affect the HTTP status code (it stays 200).
