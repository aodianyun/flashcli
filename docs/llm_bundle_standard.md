# LLM bundle standard (OpenAI + Anthropic serve)

<p align="right"><strong>English</strong> · <a href="llm_bundle_standard.zh-CN.md">简体中文</a></p>

> **Archived.** This page is kept for historical reference only and is not part
> of the doc index. The authoritative spec is
> [bundle_serve_protocols.md](bundle_serve_protocols.md).

Applies to model bundles served by `flashcli serve` that expose OpenAI and/or
Anthropic APIs: text LLMs, embeddings, moderation, audio, images, video, and
realtime. Generic packaging (manifest, directory layout, `.so`, weights,
publishing) is defined in [bundle_publish_standard.md](bundle_publish_standard.md);
entry backends are defined in [bundle_execution_abi.md](bundle_execution_abi.md).

## 1. Ownership

The host owns the HTTP surface. The bundle owns inference.

| Layer | Owns |
|-------|------|
| `flashcli` host | HTTP routes, request/response parsing, SSE, WebSocket transport, capability gating, single GPU slot, request logging |
| Bundle `ServeEngine` | Weights, chat template, tool/reasoning parsing, decoding, model-specific extras |
| `register_routes(app)` | Optional custom routes; mounted before host routes and keeps priority |

Bundles must **not** start their own `uvicorn`/`FastAPI` server. Use
`register_routes` only for endpoints the host does not provide.

## 2. Manifest

```json
"entry": {
  "serve": {
    "kind": "python",
    "module": "serve",
    "attr": "ServeEngine",
    "mode": "engine",
    "capabilities": ["openai.chat", "anthropic.messages"]
  }
}
```

| Rule | Behavior |
|------|----------|
| `capabilities` absent | Legacy default: `["openai.chat"]` |
| `capabilities: []` | Only `/health`, `/v1/models`, and `/v1/models/{id}`; no inference routes |
| Non-python or non-engine serve | `capabilities` is invalid |
| Unknown or duplicate ID | `flashcli bundle validate` fails |
| Declared but host-unimplemented | HTTP `501` (`capability_not_implemented`) |
| `--host` / `--port` | Provided by the host; never declare `ip`/`host`/`port` in `serve_options` |

## 3. Capability to endpoint to engine method

| Capability | Host endpoint | Engine method |
|------------|---------------|---------------|
| `openai.chat` | `POST /v1/chat/completions` | `chat` / `chat_stream` |
| `openai.completions` | `POST /v1/completions` | `chat` / `chat_stream` |
| `openai.responses` | `POST /v1/responses` | `chat` / `chat_stream` |
| `openai.embeddings` | `POST /v1/embeddings` | `embed` |
| `openai.moderations` | `POST /v1/moderations` | `moderate` |
| `openai.audio.transcriptions` | `POST /v1/audio/transcriptions` | `transcribe(task="transcribe")` |
| `openai.audio.translations` | `POST /v1/audio/translations` | `transcribe(task="translate")` |
| `openai.audio.speech` | `POST /v1/audio/speech` | `speech` |
| `openai.images.generations` | `POST /v1/images/generations` | `generate_images(mode="generate")` |
| `openai.images.edits` | `POST /v1/images/edits` | `generate_images(mode="edit")` |
| `openai.images.variations` | `POST /v1/images/variations` | `generate_images(mode="variation")` |
| `openai.videos` | `GET/POST /v1/videos`, `GET/DELETE /v1/videos/{id}` | `create_video` / `list_videos` / `get_video` / `download_video` / `delete_video` |
| `openai.realtime` | `WS /v1/realtime` | `realtime_session` (optional) |
| `anthropic.messages` | `POST /v1/messages` | `chat` / `chat_stream` |
| `anthropic.count_tokens` | `POST /v1/messages/count_tokens` | `count_tokens` |
| `anthropic.models` | `GET /v1/models` (with `anthropic-version`) and `GET /v1/models/{id}` | `model_id` |

`/health`, `GET /v1/models`, and `GET /v1/models/{id}` are always available.
Model list/retrieve return the OpenAI shape by default and the Anthropic shape
when the `anthropic-version` header is present and `anthropic.models` is
declared.

## 4. `ServeEngine` contract

Required members:

```python
class ServeEngine:
    model_id: str
    def load(self, checkpoint: Path, preset: Preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def chat(self, request: ChatRequest) -> ChatResult: ...
    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...
```

Optional async variants take precedence when present:
`chat_async(request) -> ChatResult` and
`chat_stream_async(request) -> AsyncIterator[ChatChunk]`.

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

A missing optional method returns HTTP `501`. When `realtime_session` is
absent the host runs its own text state machine (session, conversation items,
input audio buffer with optional `transcribe`, response create/cancel); a
present handler takes over the full event protocol. Raising
`NotImplementedError`/other exceptions surfaces as the protocol error for that
endpoint.

## 5. Request mapping

- `ChatRequest.extras` carries protocol fields the host does not interpret:
  `tool_choice`, `response_format`, sampling penalties, `user`, Responses
  `reasoning`/`truncation`/`parallel_tool_calls`, and Anthropic thinking
  parameters. Bundles must apply them to their template or upstream body.
- Anthropic `tool_choice` is normalized to the OpenAI form
  (`auto` / `required` / `none` / `{"type": "function", "function": {"name": ...}}`).
- Anthropic content blocks are mapped to host chat messages: `image` → image
  URL part, `tool_use` → assistant tool call, `tool_result` → tool message,
  `thinking`/`redacted_thinking` → reasoning, `document` → text.
- Anthropic `cache_control` markers are preserved on system, text, image, and
  tool-result parts; images inside `tool_result` blocks are kept as image parts.
- OpenAI `n > 1` is supported for chat and completions, streaming and
  non-streaming (the host runs the engine `n` times and merges usage).
- `/v1/completions` rejects empty prompts and `logprobs`, `best_of`, `suffix`.
- Responses `input_file` accepts `file_data` (base64 or inline UTF-8 text);
  `file_id` needs the Files API and returns `501`. `background: true` runs the
  request asynchronously and supports retrieve/cancel/delete.
- Realtime: with no `realtime_session`, the host serves the text state machine;
  audio input is buffered and transcribed through `transcribe` when available.
  A bundle handler replaces the host state machine entirely.

## 6. Compatibility

- Legacy manifests without `serve.capabilities` keep only `openai.chat`
  (plus `/health` and `/v1/models`). Declare capabilities to enable Anthropic,
  Responses, audio, images, video, and Realtime.
- `register_routes` and custom endpoints are unaffected by capability gating.
- Unknown capability IDs fail validation instead of being silently ignored.

## 7. Validation and tests

```bash
flashcli bundle validate <bundle-or-dist>
pytest tests/test_serve_protocols.py tests/test_serve_protocol_matrix.py
```

Before publishing, run the published tree through `flashcli serve` and verify
at least: non-streaming + streaming chat, tools and `tool_choice`, Anthropic
messages + streaming events, `count_tokens`, and every declared non-chat
capability. Use `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` to tune busy behavior
(see [environment.md](environment.md)).

## Related docs

- [bundle_publish_standard.md](bundle_publish_standard.md) — manifest, layout, publishing
- [bundle_execution_abi.md](bundle_execution_abi.md) — `entry.kind` backends
- [openapi.yaml](openapi.yaml) — host HTTP surface for `flashserver` (not bundle serve)
- [bundle_builder_guide.md](bundle_builder_guide.md) — build and release workflow
