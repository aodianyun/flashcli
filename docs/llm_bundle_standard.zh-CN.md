# LLM bundle 标准（OpenAI + Anthropic serve）

<p align="right"><a href="llm_bundle_standard.md">English</a> · <strong>简体中文</strong></p>

> **已归档。** 本页仅保留作历史参考，不在文档索引中。权威规范见
> [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)。

适用于通过 `flashcli serve` 对外提供 OpenAI 和/或 Anthropic API 的模型 bundle：
文本 LLM、embedding、moderation、音频、图像、视频和 realtime。通用打包规则
（manifest、目录结构、`.so`、权重、发布）见
[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)；entry 后端见
[bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。

## 1. 职责归属

Host 负责 HTTP 接口，bundle 负责推理。

| 层 | 负责 |
|----|------|
| `flashcli` host | HTTP 路由、请求/响应解析、SSE、WebSocket transport、能力门控、`serve.concurrency` 推理槽位（默认 1）、请求日志 |
| Bundle `ServeEngine` | 权重、chat template、工具/推理解析、解码、模型专属扩展 |
| `register_routes(app)` | 可选自定义路由；挂在 host 路由之前并保持优先 |

Bundle **不得**自行启动 `uvicorn`/`FastAPI` 服务。仅对 host 未提供的端点使用
`register_routes`。

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

| 规则 | 行为 |
|------|------|
| 缺省 `capabilities` | 兼容默认：`["openai.chat"]` |
| `capabilities: []` | 仅保留 `/health`、`/v1/models`、`/v1/models/{id}`，无推理路由 |
| 非 python 或非 engine serve | `capabilities` 非法 |
| 未知或重复 ID | `flashcli bundle validate` 失败 |
| 已声明但 host 未实现 | HTTP `501`（`capability_not_implemented`） |
| `--host` / `--port` | 由 host 提供；禁止在 `serve_options` 声明 `ip`/`host`/`port` |

## 3. 能力 → 端点 → engine 方法

| 能力 | Host 端点 | Engine 方法 |
|------|-----------|-------------|
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
| `openai.videos` | `GET/POST /v1/videos`、`GET/DELETE /v1/videos/{id}` | `create_video` / `list_videos` / `get_video` / `download_video` / `delete_video` |
| `openai.realtime` | `WS /v1/realtime` | `realtime_session`（可选） |
| `anthropic.messages` | `POST /v1/messages` | `chat` / `chat_stream` |
| `anthropic.count_tokens` | `POST /v1/messages/count_tokens` | `count_tokens` |
| `anthropic.models` | `GET /v1/models`（带 `anthropic-version`）与 `GET /v1/models/{id}` | `model_id` |

`/health`、`GET /v1/models`、`GET /v1/models/{id}` 始终可用。模型列表/检索默认返回
OpenAI 结构；当声明 `anthropic.models` 且请求带 `anthropic-version` 头时返回
Anthropic 结构。

## 4. `ServeEngine` 契约

必需成员：

```python
class ServeEngine:
    model_id: str
    def load(self, checkpoint: Path, preset: Preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def chat(self, request: ChatRequest) -> ChatResult: ...
    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...
```

可选异步版本优先：`chat_async(request) -> ChatResult` 与
`chat_stream_async(request) -> AsyncIterator[ChatChunk]`。

可选能力方法（鸭子类型；同步返回值或 awaitable）：

| 方法 | 请求 / 结果 |
|------|-------------|
| `embed(EmbeddingRequest)` | `EmbeddingResult`；每个输入一个 embedding |
| `moderate(ModerationRequest)` | `ModerationResult`；每个输入一个结果 |
| `transcribe(AudioTranscriptionRequest)` | `AudioTranscriptionResult` |
| `speech(SpeechRequest)` | `SpeechResult` |
| `generate_images(ImageGenerationRequest)` | `ImageGenerationResult` |
| `create_video(VideoRequest)` | 含 `id` 的 job `dict` |
| `list_videos()` | job `dict` 列表 |
| `get_video(id)` | job `dict`；未知时抛 `KeyError` |
| `download_video(id)` | `bytes` |
| `delete_video(id)` | `bool` |
| `count_tokens(ChatRequest)` | `int` |
| `realtime_session(websocket, model)` | Realtime 事件协议的 async handler |

缺少可选方法时返回 HTTP `501`。未提供 `realtime_session` 时，host 运行自带的文本状态机
（session、conversation item、输入音频缓冲 + 可选 `transcribe`、response create/cancel）；
提供 handler 时由 bundle 接管完整事件协议。抛出 `NotImplementedError` 或其他异常按该端点
的协议错误返回。

## 5. 请求映射

- `ChatRequest.extras` 承载 host 不解释的协议字段：`tool_choice`、
  `response_format`、采样 penalty、`user`、Responses 的
  `reasoning`/`truncation`/`parallel_tool_calls`，以及 Anthropic thinking 参数。
  Bundle 必须把它们应用到 template 或上游请求体。
- Anthropic `tool_choice` 归一化为 OpenAI 形式
  （`auto` / `required` / `none` / `{"type": "function", "function": {"name": ...}}`）。
- Anthropic content block 映射为 host chat message：`image` → 图片 URL part，
  `tool_use` → assistant tool call，`tool_result` → tool message，
  `thinking`/`redacted_thinking` → reasoning，`document` → 文本。
- Anthropic `cache_control` 标记在 system、text、image、tool_result part 上保留；
  `tool_result` 内的图片保留为 image part。
- OpenAI `n > 1` 对 chat 与 completions 的流式和非流式均支持（host 调用 engine `n`
  次并合并 usage）。
- `/v1/completions` 拒绝空 prompt 以及 `logprobs`、`best_of`、`suffix`。
- Responses `input_file` 支持 `file_data`（base64 或内联 UTF-8 文本）；`file_id`
  需要 Files API，返回 `501`。`background: true` 异步执行，支持 retrieve/cancel/delete。
- Realtime：未提供 `realtime_session` 时由 host 提供文本状态机；音频输入会缓冲，并在
  engine 支持 `transcribe` 时转写。提供 handler 时宿主状态机被完全替换。

## 6. 兼容性

- 没有 `serve.capabilities` 的旧 manifest 仅保留 `openai.chat`
  （外加 `/health` 与 `/v1/models`）。要启用 Anthropic、Responses、音频、图像、视频和
  Realtime，必须显式声明对应能力。
- `register_routes` 与自定义端点不受能力门控影响。
- 未知能力 ID 会使校验失败，而不是被静默忽略。

## 7. 校验与测试

```bash
flashcli bundle validate <bundle-or-dist>
pytest tests/test_serve_protocols.py tests/test_serve_protocol_matrix.py
```

发布前用发布树执行 `flashcli serve`，至少验证：非流式 + 流式 chat、工具与
`tool_choice`、Anthropic messages + 流式事件、`count_tokens`，以及所有已声明的非 chat
能力。忙时行为可通过 `FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` 调整
（见 [environment.zh-CN.md](environment.zh-CN.md)）。

## 相关文档

- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) —— manifest、目录、发布
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) —— `entry.kind` 后端
- [openapi.yaml](../go/internal/server/openapi.yaml) —— `flashserver` 的 host HTTP 契约（非 bundle serve）
- [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) —— 构建与发布流程
