# Bundle serve protocol integration (OpenAI + Anthropic)

<p align="right"><strong>English</strong> · <a href="bundle_serve_protocols.zh-CN.md">简体中文</a></p>

**Scope: Python `serve` entry in `engine` mode (`ServeEngine`).** In this mode
the host owns the HTTP/WebSocket surface and mounts OpenAI/Anthropic routes
according to `serve.capabilities`. Other serve entry forms own the server
themselves; see [§1](#1-integration-modes-read-first).

Manifest, layout, and publishing rules live in
[bundle_publish_standard.md](bundle_publish_standard.md); entry backends live in
[bundle_execution_abi.md](bundle_execution_abi.md).

## 1. Integration modes (read first)

`entry.serve` can be Python or native, and Python has `engine`/`script` modes.
Only **Python + engine** gets the host-owned protocol surface described in this
document.

| `entry.serve` | Host HTTP/WS server | Who implements OpenAI/Anthropic | `serve.capabilities` |
|---------------|---------------------|--------------------------------|----------------------|
| `kind:"python"`, `mode:"engine"` | Host (`build_app` + uvicorn) | Host routes + `ServeEngine` methods | **Valid; this document** |
| `kind:"python"`, `mode:"script"` | None (bundle runs its own) | Bundle `main(argv)` | Invalid |
| `kind:"native-exec"`, `transport:"http"` | None (host supervises) | Bundle process endpoint | Not applicable |
| `kind:"native-exec"`, `transport:"stdio"` | — | Serve not implemented | Not applicable |
| `kind:"native-abi"` | — | Serve not implemented | Not applicable |

**Engine mode (this document).** The host loads `ServeEngine`, calls
`load`/`warmup`, builds the FastAPI app, and mounts routes by capability.
`/health` and the model endpoints are host-owned.

**Script mode is bundle-owned.** The host only prepares the bundle/weights,
injects `FLASHCLI_CHECKPOINT` / `FLASHCLI_BUNDLE_ROOT` / `FLASHCLI_PRESET`, and
forwards the remaining argv (including `--host`/`--port`) to
`main(argv)`. The script must start and own its HTTP server, routes, SSE/WS,
auth, errors, `/health`, and model endpoints. The host does not mount
`/health`, `/v1/models`, or any OpenAI/Anthropic route. `serve.capabilities` is
invalid for script mode (`bundle validate` rejects it), and `serve_options` are
documentation-only.

**Native serve.** `native-exec` with `transport:"http"` is spawned, awaited for
readiness, then supervised; the host prints the bundle endpoint and does not
proxy, so the bundle owns the entire protocol. `native-exec` over stdio and
`native-abi` serve are not implemented yet.

The remainder of this document describes **only Python engine mode**.

## 2. Ownership (engine mode)

| Layer | Owns |
|-------|------|
| Host | HTTP/WS routing, request parsing, SSE/WS transport, capability gating, `serve.concurrency` inference slots (default 1), request log, protocol-error translation |
| Bundle `ServeEngine` | Weights, chat template, tools/reasoning parsing, decoding, model-specific extras |
| `register_routes(app)` | Optional custom routes; mounted before host routes and keeps priority |

In engine mode bundles must not start their own `uvicorn`/`FastAPI` server.

## 3. Capability declaration (engine mode)

```json
"entry": {
  "serve": {
    "kind": "python",
    "module": "serve",
    "attr": "ServeEngine",
    "mode": "engine",
    "capabilities": ["openai.chat", "anthropic.messages"],
    "concurrency": 1
  }
}
```

| Rule | Behavior |
|------|----------|
| `capabilities` absent | Legacy default: `["openai.chat"]` |
| `capabilities: []` | Only `/health`, `/v1/models`, `/v1/models/{id}` |
| `concurrency` absent | `1` (one host-owned inference call at a time) |
| `concurrency: N` | Up to `N` simultaneous inference calls; `N >= 1`. `N > 1` requires async gated methods; sync methods are rejected |
| Non-python or non-engine serve | `capabilities` / `concurrency` invalid |
| Unknown or duplicate ID | `bundle validate` fails |
| Declared but host-unimplemented | HTTP `501` (`capability_not_implemented`) |
| `--host` / `--port` | Provided by host; never declare `ip`/`host`/`port` in `serve_options` |

### Capability → endpoint → engine method

| Capability | Endpoint(s) | Engine method |
|------------|-------------|---------------|
| `openai.chat` | `POST /v1/chat/completions` | `chat` / `chat_stream` |
| `openai.completions` | `POST /v1/completions` | `chat` / `chat_stream` |
| `openai.responses` | `POST /v1/responses`; `GET/DELETE /v1/responses/{id}`; `POST /v1/responses/{id}/cancel` | `chat` / `chat_stream` |
| `openai.embeddings` | `POST /v1/embeddings` | `embed` |
| `openai.moderations` | `POST /v1/moderations` | `moderate` |
| `openai.audio.transcriptions` | `POST /v1/audio/transcriptions` | `transcribe(task="transcribe")` |
| `openai.audio.translations` | `POST /v1/audio/translations` | `transcribe(task="translate")` |
| `openai.audio.speech` | `POST /v1/audio/speech` | `speech` |
| `openai.images.generations` | `POST /v1/images/generations` | `generate_images(mode="generate")` |
| `openai.images.edits` | `POST /v1/images/edits` | `generate_images(mode="edit")` |
| `openai.images.variations` | `POST /v1/images/variations` | `generate_images(mode="variation")` |
| `openai.videos` | `GET/POST /v1/videos`; `GET/DELETE /v1/videos/{id}`; `GET /v1/videos/{id}/content` | `create_video` / `list_videos` / `get_video` / `download_video` / `delete_video` |
| `openai.realtime` | `WS /v1/realtime` | `realtime_session` (optional) |
| `anthropic.messages` | `POST /v1/messages` | `chat` / `chat_stream` |
| `anthropic.count_tokens` | `POST /v1/messages/count_tokens` | `count_tokens` |
| `anthropic.models` | `GET /v1/models` (with `anthropic-version`); `GET /v1/models/{id}` | `model_id` |

`/health`, `GET /v1/models`, and `GET /v1/models/{id}` are always available in
engine mode.

Declaring a capability requires every engine method listed for it. In
particular, `openai.videos` requires `create_video`, `list_videos`,
`get_video`, `download_video`, and `delete_video`; the three image capabilities
all require `generate_images`; audio requires `transcribe` / `speech`; and
`anthropic.count_tokens` requires `count_tokens`. These are checked when the
engine loads.

## 4. `ServeEngine` contract (engine mode)

Always required:

```python
class ServeEngine:
    model_id: str
    def load(self, checkpoint: Path, preset: Preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
```

All host-owned inference routes share one gate sized by `serve.concurrency`.
With `N > 1`, async engine methods (`chat_async`, async `embed` / `transcribe` /
`speech` / `generate_images` / video methods) can overlap. Sync gated methods are
**rejected** when `N > 1`; use `N = 1` for a synchronous engine.

### Concurrency requirements (`serve.concurrency > 1`)

Only async engine methods overlap. A bundle opting into `N > 1` must:

- implement `chat_async` / `chat_stream_async` for chat capabilities, and
  `async def` for `embed`, `moderate`, `transcribe`, `speech`,
  `generate_images`, and the video methods it declares;
- support overlapping requests and streams: no single-in-flight assumption,
  independent per-request state, and enough GPU memory / KV cache for `N`
  calls;
- keep `load` / `warmup` outside the gate (the host calls them once);
- treat `create_video` as the gated call; engine-owned background rendering
  runs outside the gate.

Synchronous gated methods are rejected when `N > 1`; use `N = 1` for a
synchronous engine. When all `N` slots are occupied, requests wait or return
`503` according to `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC`.

### Per-API concurrency behavior

The gate is **per serve process**. `n` choices, prompt arrays, and other work
inside one request are sequential; `concurrency` allows different requests to
overlap.

| API | Uses an inference slot | Async method(s) | Notes |
|-----|------------------------|-----------------|-------|
| `/health`, `/v1/models`, `/v1/models/{id}` | no | — | Always available |
| `POST /v1/chat/completions` | yes | `chat_async` / `chat_stream_async` | Slot held for the request or the whole SSE stream; `n` choices are sequential |
| `POST /v1/completions` | yes | `chat_async` / `chat_stream_async` | Prompts × `n` are sequential inside one request |
| `POST /v1/responses` | yes | `chat_async` / `chat_stream_async` | Streaming holds the slot; a background response holds it while running |
| `POST /v1/messages` | yes | `chat_async` / `chat_stream_async` | Anthropic SSE holds the slot |
| `POST /v1/embeddings` | yes | `embed` | One engine call per request |
| `POST /v1/moderations` | yes | `moderate` | One engine call per request |
| `POST /v1/audio/transcriptions` / `translations` | yes | `transcribe` | One engine call per request |
| `POST /v1/audio/speech` | yes | `speech` | One engine call per request |
| `POST /v1/images/*` | yes | `generate_images` | One engine call per request; `n` is handled by the engine |
| `POST /v1/videos` | yes | `create_video` | Only the create call is gated |
| `GET/DELETE /v1/videos*`, `/v1/videos/{id}/content` | no | — | Job metadata/download; engine background work is outside the gate |
| `WS /v1/realtime` | yes | `realtime_session` or `chat_async` | One slot per `response.create`; `N > 1` allows multiple sessions |
| `POST /v1/messages/count_tokens` | no | `count_tokens` | Metadata operation |
| `register_routes` custom endpoints | no | Bundle-owned | Not gated |
| `load` / `warmup` | no | — | Called once by the host before serving |
`/health`, `/v1/models`, `count_tokens`, and video list/get/download/delete are
metadata operations and do not take an inference slot; video creation does.

`chat` / `chat_stream` are required only when declaring a chat-based capability
(`openai.chat`, `openai.completions`, `openai.responses`, `anthropic.messages`)
or `openai.realtime` without a bundle `realtime_session` handler. Modality-only
bundles (ASR/TTS/image/video/embedding-only) do **not** need chat stubs.

```python
    def chat(self, request: ChatRequest) -> ChatResult: ...
    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...
```

Chat capabilities require `chat` + `chat_stream`, or the async variants
`chat_async` + `chat_stream_async`. Optional async variants take precedence:
`chat_async(request) -> ChatResult`, `chat_stream_async(request) -> AsyncIterator[ChatChunk]`.

Optional capability methods (duck-typed; sync return or awaitable):

| Method | Request / result |
|--------|------------------|
| `embed(EmbeddingRequest)` | `EmbeddingResult`; one embedding per input |
| `moderate(ModerationRequest)` | `ModerationResult`; one result per input |
| `transcribe(AudioTranscriptionRequest)` | `AudioTranscriptionResult` |
| `speech(SpeechRequest)` | `SpeechResult` |
| `generate_images(ImageGenerationRequest)` | `ImageGenerationResult` |
| `create_video(VideoRequest)` | job `dict` with `id` |
| `list_videos()` | list of job `dict`s |
| `get_video(id)` | job `dict`; raise `KeyError` when unknown |
| `download_video(id)` | `bytes` |
| `delete_video(id)` | `bool` |
| `count_tokens(ChatRequest)` | `int` |
| `realtime_session(websocket, model)` | async handler for the Realtime event protocol |

Declared capabilities require their methods when the engine loads; missing
members fail serve startup. The host still returns `501` defensively if a
declared method is unavailable at request time. `realtime_session` is optional:
when absent the host runs its own text state machine (session, items, audio
buffer with optional `transcribe`, response create/cancel); a present handler
takes over the full event protocol. Other exceptions surface as the endpoint's
protocol error.

## 5. OpenAI integration (engine mode)

### 5.0 Shared conventions

- `model` may be any value; chat/completions/responses use `engine.model_id` in responses.
- Errors: `400` invalid request, `404` unknown resource, `500` inference error,
  `501` host-unimplemented or defensively missing engine method, `503` +
  `Retry-After: 5` when GPU busy.
- SSE streams end with `data: [DONE]`.
- Unknown request fields are collected in `ChatRequest.extras` for the bundle.

### 5.1 `POST /v1/chat/completions`

| Input | Notes |
|-------|-------|
| `messages` | Required, non-empty; `role`, `content`, `tool_calls`, `tool_call_id`, `name` |
| `max_tokens` / `max_completion_tokens` | Default 256 |
| `temperature`, `top_p`, `top_k`, `stop` (string or array), `seed` | Mapped to `ChatRequest` |
| `stream` | SSE |
| `tools` | Function tools |
| `n` | ≥ 1; multiple choices for streaming and non-streaming |
| `tool_choice`, `response_format`, `logprobs`, penalties, `user` | Passed through `extras` |

Output (non-stream): `chat.completion` with `choices[{index, message, finish_reason}]`
and `usage`. `message` carries `content`, optional `reasoning_content`, `tool_calls`.

Output (stream): `chat.completion.chunk` events; first chunk carries `role`
(`reasoning_content`/`reasoning` when thinking is enabled, else `content`), then
delta events, a finish chunk (`usage` when provided), and `[DONE]`. `choices[].index`
distinguishes `n>1` choices.

### 5.2 `POST /v1/completions`

| Input | Notes |
|-------|-------|
| `prompt` | String or string array; empty string/array → `400` |
| `max_tokens`, `temperature`, `top_p`, `stop`, `seed`, `stream`, `n`, `echo` | Mapped |
| `logprobs`, `best_of`, `suffix` | Unsupported → `400` |

Output: `text_completion` / SSE text deltas. Choice count = prompts × `n`.

### 5.3 `POST /v1/responses`

| Input | Notes |
|-------|-------|
| `input` | String or item array |
| Items | `message` (`input_text`/`output_text`/`text`, `input_image`, `input_file`), `function_call`, `function_call_output`, `reasoning` |
| `input_file` | `file_data` base64 or inline UTF-8 text; `file_id` → `501` |
| `instructions` | System message |
| `max_output_tokens`, `temperature`, `top_p` | Mapped |
| `tools`, `tool_choice` | Function tools only; other types → `400` |
| `previous_response_id` | Replays stored conversation; unknown → `400` |
| `metadata`, `store` | Stored in memory; `store:false` disables retrieval |
| `text.format` | Mapped to `response_format` in extras |
| `reasoning`, `truncation`, `parallel_tool_calls` | Passed through extras |
| `background` | Async execution; with `stream` → `400` |

Output: `response` object with `status` (`completed`/`incomplete`), `output`
(`reasoning`/`message`/`function_call`), `output_text`, `usage`. Streaming emits
`response.created`, `in_progress`, output item/content part add/done,
`output_text.delta/done`, reasoning deltas, `function_call_arguments.done`,
`response.completed`/`failed`.

| Extra endpoint | Output |
|----------------|--------|
| `GET /v1/responses/{id}` | Stored response or `404` |
| `DELETE /v1/responses/{id}` | `{id, object:"response.deleted", deleted:true}` |
| `POST /v1/responses/{id}/cancel` | Cancels a running background response; completed/missing → `400`/`404` |

`finish_reason == "length"` produces `status:"incomplete"`.

### 5.4 `POST /v1/embeddings`

Input: `input` string / string[] / token array / token-array array; `dimensions`;
`encoding_format` `float` or `base64` (little-endian float32). Output: `list` with
`data[{object:"embedding", embedding, index}]`, `model`, `usage`. Mismatched
engine output count → `500`; a declared embeddings capability without `embed`
fails startup, with a defensive `501` if the method disappears at runtime.

### 5.5 `POST /v1/moderations`

Input: `input` string/string[]. Output: `id`, `model`, `results[]`, `usage`.

### 5.6 Audio

| Endpoint | Input | Output |
|----------|-------|--------|
| `POST /v1/audio/transcriptions` | multipart `file` (required), `model`, `language`, `prompt`, `response_format` (`json`/`text`/`srt`/`vtt`/`verbose_json`), `temperature`, `timestamp_granularities[]` | JSON/text/subtitle; `verbose_json` with `task:"transcribe"`, segments, words |
| `POST /v1/audio/translations` | Same multipart fields | Same, `verbose_json` uses `task:"translate"` |
| `POST /v1/audio/speech` | JSON `input` (required), `model`, `voice`, `response_format` (mp3/opus/aac/flac/wav/pcm), `speed`, `instructions` | Audio bytes with media type |

### 5.7 Images

| Endpoint | Input | Output |
|----------|-------|--------|
| `POST /v1/images/generations` | JSON `prompt` (required), `model`, `n`, `size`, `quality`, `style`, `response_format` | `{created, data:[{url|b64_json, revised_prompt?}], usage}` |
| `POST /v1/images/edits` | multipart `image` (required), `mask`, `prompt` (required), plus common fields | Same |
| `POST /v1/images/variations` | multipart `image` (required), plus common fields | Same |

`url` output is a `data:image/...;base64,...` URI.

### 5.8 Videos

| Endpoint | Input | Output |
|----------|-------|--------|
| `POST /v1/videos` | JSON or multipart: `prompt`, `model`, `seconds`, `size`, optional `input_reference` | job `{id, object:"video", status, created_at, ...}` |
| `GET /v1/videos` | `limit` 1–100 (default 20) | `{object:"list", data:[job], has_more}` |
| `GET /v1/videos/{id}` | — | job or `404` |
| `GET /v1/videos/{id}/content` | — | `video/mp4` bytes |
| `DELETE /v1/videos/{id}` | — | `{id, object:"video.deleted", deleted:bool}` |

### 5.9 `WS /v1/realtime`

If the bundle implements `realtime_session(websocket, model)`, it owns the full
event protocol; the host only accepts, selects the model, gates the capability,
and forwards errors.

Without a handler the host serves a text state machine:

| Direction | Events |
|-----------|--------|
| Client → server | `session.update`, `conversation.item.create/delete/truncate`, `input_audio_buffer.append/commit/clear`, `response.create`, `response.cancel` |
| Server → client | `session.created/updated`, `conversation.item.created/deleted/truncated`, `input_audio_buffer.committed/cleared`, `response.created`, `response.output_item.added/done`, `response.content_part.added/done`, `response.output_text.delta/done`, `response.function_call_arguments.done`, `response.done`, `error` |

`session.update` accepts known fields only (`id`/`object`/`model` immutable).
`response.create` accepts `response` overrides (`instructions`, `tools`,
`tool_choice`, `temperature`, `max_output_tokens`). Audio appends are buffered;
`commit` creates an input item and transcribes via `transcribe` when available.

### 5.10 Models

`GET /v1/models` and `GET /v1/models/{id}` are always available in engine mode.
They return the OpenAI shape by default and the Anthropic shape when
`anthropic-version` is present and `anthropic.models` is declared. Unknown id →
`404` (`model_not_found` / `not_found_error`).

## 6. Anthropic integration (engine mode)

### 6.1 `POST /v1/messages`

| Input | Notes |
|-------|-------|
| `messages` | Required, non-empty |
| Blocks | `text` (`cache_control` preserved), `image` (base64/url, `cache_control`), `tool_use`, `tool_result` (text/image/`is_error`/`cache_control`), `thinking`/`redacted_thinking`, `document` |
| `system` | String or blocks; `cache_control` preserved |
| `max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences` | Mapped |
| `stream` | SSE |
| `tools` | `{name, description, input_schema}` → OpenAI function |
| `tool_choice` | `auto`→`auto`, `any`→`required`, `none`→`none`, `tool`→function object |
| `thinking` | `anthropic_thinking` in extras; `enable_thinking` derived from `type != "disabled"` |
| `metadata` etc. | Extras |

Output (non-stream): `message` with `content` blocks `thinking`/`text`/`tool_use`,
`stop_reason` (`end_turn`, `max_tokens`, `tool_use`, `stop_sequence`, `refusal`),
`usage{input_tokens, output_tokens}`.

Output (stream): SSE `message_start`, `content_block_start`, `content_block_delta`
(`thinking_delta`/`text_delta`/`input_json_delta`), `content_block_stop`,
`message_delta`, `message_stop`, `error`.

`tool_result` images are kept as image parts; `cache_control` is preserved on
system, text, image, and tool-result parts.

### 6.2 `POST /v1/messages/count_tokens`

Same validation as messages. Output `{input_tokens:int}`. A declared
`anthropic.count_tokens` capability without `count_tokens` fails startup;
counter error → `500`, with a defensive `501` if the method disappears at
runtime.

### 6.3 Models

`GET /v1/models` supports `limit` (1–1000) and `before_id`/`after_id`; a
single-model host returns an empty page for any cursor. `GET /v1/models/{id}`
returns the Anthropic shape with `anthropic-version`.

## 7. Shared translation rules (engine mode)

| Area | Rule |
|------|------|
| `extras` | `tool_choice`, `response_format`, penalties, `user`, Responses control fields, Anthropic thinking parameters are forwarded to the bundle |
| `tool_choice` | Anthropic normalized to OpenAI form |
| Multimodal | Anthropic image blocks → image URL parts; tool-result images preserved |
| Reasoning | `reasoning_content` on results; `thinking` blocks / `reasoning` items on output |
| `n > 1` | Chat and completions support streaming and non-streaming; usage merged |
| Usage | Chat/responses derive from engine usage; missing keys default to 0 |
| Busy | `serve.concurrency` inference slots; `503` with `Retry-After: 5` |

## 8. Compatibility and gating (engine mode)

- Legacy manifests without `serve.capabilities` keep only `openai.chat`.
- `[]` keeps only health/models; no inference routes.
- `register_routes` custom endpoints are not gated.
- Unknown capability IDs fail validation.
- Script and native serve entries do not use this gating model; they own their
  own endpoints.

## 9. Validation and acceptance (engine mode)

```bash
flashcli bundle validate <bundle-or-dist>
pytest tests/test_serve_protocol_matrix.py tests/test_serve_realtime.py tests/test_serve_concurrency.py

# Real bundle acceptance: builds llm/code/anthropic/asr/tts/audio/image/video/legacy fixtures,
# starts each through flashcli-bundle.infer serve, and exercises real sockets.
FLASHCLI_ACCEPTANCE=1 pytest tests/acceptance/test_serve_bundles.py
```

`flashcli bundle validate` is a static manifest/file check: capability IDs,
duplicates, concurrency value, and entry module existence. When a Python
interpreter is available (no venv required), it also performs a best-effort AST
check of directly defined `ServeEngine` classes against the declared capability
methods, including async gated methods when `concurrency > 1`. Imported,
inherited, or dynamic classes and missing Python interpreters are skipped;
`flashcli serve` and `flashserver` remain authoritative. A bundle that declares
a capability without implementing its methods fails `bundle validate` when the
class is directly visible, and always fails serve startup. Use
`--skip-static-serve` to skip the AST check; set `FLASHCLI_PYTHON` to choose the
interpreter.

Before publishing, run the published tree through `flashcli serve` and verify
non-streaming + streaming chat, tools and `tool_choice`, Anthropic messages and
streaming events, `count_tokens`, and every declared non-chat capability.

## 10. Known limitations

These apply to the **engine-mode host surface**; script/native serve can
implement anything in the bundle.

| Area | Limitation |
|------|------------|
| Chat | `logprobs`/`response_format` forwarded, not produced/enforced |
| Completions | `logprobs`/`best_of`/`suffix` rejected |
| Responses | `file_id`/non-text files unsupported; no input_items/input_tokens/include; no built-in tools; background is in-memory |
| Audio | No streaming transcription/chunking; no streaming speech |
| Images | No stream/background/output format controls |
| Videos | No remix or cursor pagination |
| Realtime | Text state machine; no TTS/VAD/audio output; reasoning not emitted |
| Anthropic | No batches/files/MCP/container/context_management/output_config; `disable_parallel_tool_use` dropped |
| Platform APIs | OpenAI Batch/Files/Fine-tuning/Assistants/Vector Stores are out of scope |
| Auth/limits | Local single-user CLI; intentionally omitted |
| Serve forms | Native `native-exec` stdio and `native-abi` serve are not implemented |
| Concurrency | `serve.concurrency > 1` requires async gated methods; sync gated methods are rejected |

## Related docs

- [bundle_publish_standard.md](bundle_publish_standard.md) — manifest, layout, publishing
- [bundle_execution_abi.md](bundle_execution_abi.md) — entry kinds and native serve behavior
- [module_layers.md](module_layers.md) — host/infer/protocol ownership
- [bundle_builder_guide.md](bundle_builder_guide.md) — build and release
