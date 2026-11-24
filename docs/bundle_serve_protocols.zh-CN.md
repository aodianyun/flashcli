# Bundle serve 协议对接（OpenAI + Anthropic）

<p align="right"><a href="bundle_serve_protocols.md">English</a> · <strong>简体中文</strong></p>

**范围：Python `serve` 入口的 `engine` 模式（`ServeEngine`）。** 只有该模式由 host 拥有
HTTP/WebSocket 接口，并按 `serve.capabilities` 挂载 OpenAI/Anthropic 路由。其他 serve
入口形式由 bundle 自行接管服务；见 [§1](#1-集成模式先读这里)。

Manifest、目录与发布规则见
[bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)；entry 后端见
[bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md)。

## 1. 集成模式（先读这里）

`entry.serve` 可以是 Python 或 native，Python 又分 `engine`/`script`。只有
**Python + engine** 才获得本文描述的 host 自有协议面。

| `entry.serve` | Host HTTP/WS 服务 | 谁实现 OpenAI/Anthropic | `serve.capabilities` |
|---------------|-------------------|--------------------------|----------------------|
| `kind:"python"`、`mode:"engine"` | Host（`build_app` + uvicorn） | Host 路由 + `ServeEngine` 方法 | **有效；本文范围** |
| `kind:"python"`、`mode:"script"` | 无（bundle 自行启动） | Bundle `main(argv)` | 非法 |
| `kind:"native-exec"`、`transport:"http"` | 无（host 仅监管） | Bundle 进程端点 | 不适用 |
| `kind:"native-exec"`、`transport:"stdio"` | — | serve 尚未实现 | 不适用 |
| `kind:"native-abi"` | — | serve 尚未实现 | 不适用 |

**Engine 模式（本文）。** Host 加载 `ServeEngine`，调用 `load`/`warmup`，构建 FastAPI
应用，并按能力挂载路由。`/health` 与模型端点为 host 自有。

**Script 模式由 bundle 全接管。** Host 只准备 bundle/权重、注入
`FLASHCLI_CHECKPOINT` / `FLASHCLI_BUNDLE_ROOT` / `FLASHCLI_PRESET`，并把剩余 argv
（含 `--host`/`--port`）透传给 `main(argv)`。脚本必须自行启动并拥有 HTTP 服务、路由、
SSE/WS、鉴权、错误、`/health` 和模型端点。Host 不会挂载 `/health`、`/v1/models` 或任何
OpenAI/Anthropic 路由。`serve.capabilities` 在 script 模式下非法（`bundle validate`
会拒绝），`serve_options` 仅为文档说明。

**Native serve。** `native-exec` + `transport:"http"` 由 host 启动、等待 ready、随后监管；
host 打印 bundle 端点且不做反向代理，协议完全由 bundle 拥有。`native-exec` stdio 与
`native-abi` 的 serve 尚未实现。

本文以下内容**仅描述 Python engine 模式**。

## 2. 职责归属（engine 模式）

| 层 | 负责 |
|----|------|
| Host | HTTP/WS 路由、请求解析、SSE/WS 传输、能力门控、`serve.concurrency` 推理槽位（默认 1）、请求日志、协议错误转换 |
| Bundle `ServeEngine` | 权重、chat template、工具/推理解析、解码、模型专属扩展 |
| `register_routes(app)` | 可选自定义路由；挂在 host 路由之前并保持优先 |

Engine 模式下 bundle 不得自行启动 `uvicorn`/`FastAPI` 服务。

## 3. 能力声明（engine 模式）

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

| 规则 | 行为 |
|------|------|
| 缺省 `capabilities` | 兼容默认：`["openai.chat"]` |
| `capabilities: []` | 仅保留 `/health`、`/v1/models`、`/v1/models/{id}` |
| 缺省 `concurrency` | `1`（同一时间一个 host 自有推理调用） |
| `concurrency: N` | 最多 `N` 个并发推理调用；`N >= 1`。`N > 1` 要求受门控方法为异步；同步方法会被拒绝 |
| 非 python 或非 engine serve | `capabilities` / `concurrency` 非法 |
| 未知或重复 ID | `bundle validate` 失败 |
| 已声明但 host 未实现 | HTTP `501`（`capability_not_implemented`） |
| `--host` / `--port` | 由 host 提供；禁止在 `serve_options` 声明 `ip`/`host`/`port` |

### 能力 → 端点 → engine 方法

| 能力 | 端点 | Engine 方法 |
|------|------|-------------|
| `openai.chat` | `POST /v1/chat/completions` | `chat` / `chat_stream` |
| `openai.completions` | `POST /v1/completions` | `chat` / `chat_stream` |
| `openai.responses` | `POST /v1/responses`；`GET/DELETE /v1/responses/{id}`；`POST /v1/responses/{id}/cancel` | `chat` / `chat_stream` |
| `openai.embeddings` | `POST /v1/embeddings` | `embed` |
| `openai.moderations` | `POST /v1/moderations` | `moderate` |
| `openai.audio.transcriptions` | `POST /v1/audio/transcriptions` | `transcribe(task="transcribe")` |
| `openai.audio.translations` | `POST /v1/audio/translations` | `transcribe(task="translate")` |
| `openai.audio.speech` | `POST /v1/audio/speech` | `speech` |
| `openai.images.generations` | `POST /v1/images/generations` | `generate_images(mode="generate")` |
| `openai.images.edits` | `POST /v1/images/edits` | `generate_images(mode="edit")` |
| `openai.images.variations` | `POST /v1/images/variations` | `generate_images(mode="variation")` |
| `openai.videos` | `GET/POST /v1/videos`；`GET/DELETE /v1/videos/{id}`；`GET /v1/videos/{id}/content` | `create_video` / `list_videos` / `get_video` / `download_video` / `delete_video` |
| `openai.realtime` | `WS /v1/realtime` | `realtime_session`（可选） |
| `anthropic.messages` | `POST /v1/messages` | `chat` / `chat_stream` |
| `anthropic.count_tokens` | `POST /v1/messages/count_tokens` | `count_tokens` |
| `anthropic.models` | `GET /v1/models`（带 `anthropic-version`）；`GET /v1/models/{id}` | `model_id` |

Engine 模式下 `/health`、`GET /v1/models`、`GET /v1/models/{id}` 始终可用。

声明能力时必须实现该能力对应的所有 engine 方法。具体来说，`openai.videos`
需要 `create_video`、`list_videos`、`get_video`、`download_video`、
`delete_video`；三个 image 能力都需要 `generate_images`；audio 需要
`transcribe` / `speech`；`anthropic.count_tokens` 需要 `count_tokens`。这些在
engine 加载时检查。

## 4. `ServeEngine` 契约（engine 模式）

始终必需：

```python
class ServeEngine:
    model_id: str
    def load(self, checkpoint: Path, preset: Preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
```

所有 host 自有推理路由共用一个由 `serve.concurrency` 决定大小的门限。
`N > 1` 时，异步引擎方法（`chat_async`、异步 `embed` / `transcribe` /
`speech` / `generate_images` / 视频方法）可以重叠执行；受门控的同步方法在
`N > 1` 时会被**拒绝**，同步引擎请使用 `N = 1`。
`/health`、`/v1/models`、`count_tokens` 以及视频的 list/get/download/delete
属于元数据操作，不占推理槽位；视频创建会占用。

### 并发要求（`serve.concurrency > 1`）

只有异步引擎方法会重叠。声明 `N > 1` 的 bundle 必须：

- chat 能力实现 `chat_async` / `chat_stream_async`，其它能力使用 `async def`
  实现 `embed`、`moderate`、`transcribe`、`speech`、`generate_images` 及所声明的
  视频方法；
- 支持重叠请求与流：不能假设同时只有一个请求，每请求状态相互独立，并为 `N`
  个调用准备足够的 GPU 显存 / KV cache；
- `load` / `warmup` 不在门限内（host 只调用一次）；
- 只有 `create_video` 调用占门限；引擎自己的后台渲染在门限之外。

受门控的同步方法在 `N > 1` 时会被拒绝；同步引擎请使用 `N = 1`。`N` 个槽位都占用时，请求按
`FLASHCLI_SERVE_BUSY_TIMEOUT_SEC` 等待或返回 `503`。

### 各 API 的并发行为

门限是**每个 serve 进程**独立。单个请求内部的 `n`、prompt 数组等仍是串行；
`concurrency` 只让不同请求重叠。

| API | 占用推理槽位 | 异步方法 | 说明 |
|-----|--------------|----------|------|
| `/health`、`/v1/models`、`/v1/models/{id}` | 否 | — | 始终可用 |
| `POST /v1/chat/completions` | 是 | `chat_async` / `chat_stream_async` | 请求或整个 SSE 流期间占槽位；`n` 个 choice 串行 |
| `POST /v1/completions` | 是 | `chat_async` / `chat_stream_async` | 单个请求内 prompt × `n` 串行 |
| `POST /v1/responses` | 是 | `chat_async` / `chat_stream_async` | 流式请求占槽位；后台响应运行期间占槽位 |
| `POST /v1/messages` | 是 | `chat_async` / `chat_stream_async` | Anthropic SSE 期间占槽位 |
| `POST /v1/embeddings` | 是 | `embed` | 每请求一次引擎调用 |
| `POST /v1/moderations` | 是 | `moderate` | 每请求一次引擎调用 |
| `POST /v1/audio/transcriptions` / `translations` | 是 | `transcribe` | 每请求一次引擎调用 |
| `POST /v1/audio/speech` | 是 | `speech` | 每请求一次引擎调用 |
| `POST /v1/images/*` | 是 | `generate_images` | 每请求一次引擎调用；`n` 由引擎处理 |
| `POST /v1/videos` | 是 | `create_video` | 只有 create 调用占槽位 |
| `GET/DELETE /v1/videos*`、`/v1/videos/{id}/content` | 否 | — | 任务元数据/下载；引擎后台渲染不在门限内 |
| `WS /v1/realtime` | 是 | `realtime_session` 或 `chat_async` | 每次 `response.create` 占一个槽位；`N > 1` 可多会话 |
| `POST /v1/messages/count_tokens` | 否 | `count_tokens` | 元数据操作 |
| `register_routes` 自定义端点 | 否 | bundle 自有 | 不受门控 |
| `load` / `warmup` | 否 | — | host 在开始服务前调用一次 |

仅当声明对话类能力（`openai.chat`、`openai.completions`、`openai.responses`、
`anthropic.messages`），或声明 `openai.realtime` 但 bundle 未提供
`realtime_session` 时才要求 `chat` / `chat_stream`。仅模态类 bundle
（ASR/TTS/图像/视频/仅 embedding）**不需要** chat 桩。

```python
    def chat(self, request: ChatRequest) -> ChatResult: ...
    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...
```

对话类能力要求 `chat` + `chat_stream`，或异步版本 `chat_async` +
`chat_stream_async`。异步版本优先：`chat_async(request) -> ChatResult`、
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

声明了能力就必须在 engine 加载时实现对应方法；缺少成员会使 serve 启动失败。
运行期若方法意外不可用，host 仍会防御性返回 `501`。未提供 `realtime_session` 时，
host 运行自带文本状态机（session、item、音频缓冲 + 可选 `transcribe`、
response create/cancel）；提供 handler 时由 bundle 接管完整事件协议。其他异常按该
端点的协议错误返回。

## 5. OpenAI 对接（engine 模式）

### 5.0 通用约定

- `model` 可为任意值；chat/completions/responses 的响应使用 `engine.model_id`。
- 错误：`400` 非法请求、`404` 未知资源、`500` 推理异常、`501` host 未实现或
  防御性缺失 engine 方法、`503` + `Retry-After: 5`（GPU busy）。
- SSE 流以 `data: [DONE]` 结束。
- 未知请求字段进入 `ChatRequest.extras`，交给 bundle。

### 5.1 `POST /v1/chat/completions`

| 输入 | 说明 |
|------|------|
| `messages` | 必填非空；`role`、`content`、`tool_calls`、`tool_call_id`、`name` |
| `max_tokens` / `max_completion_tokens` | 默认 256 |
| `temperature`、`top_p`、`top_k`、`stop`（字符串或数组）、`seed` | 映射到 `ChatRequest` |
| `stream` | SSE |
| `tools` | 函数工具 |
| `n` | ≥ 1；流式与非流式均支持多 choice |
| `tool_choice`、`response_format`、`logprobs`、penalty、`user` | 通过 `extras` 透传 |

输出（非流式）：`chat.completion`，`choices[{index, message, finish_reason}]`，`usage`。
`message` 含 `content`、可选 `reasoning_content`、`tool_calls`。

输出（流式）：`chat.completion.chunk`；首个 chunk 带 `role`（开启 thinking 时为
`reasoning_content`/`reasoning`，否则 `content`），随后 delta、finish chunk（
有 usage 时附带）、`[DONE]`。`choices[].index` 区分 `n>1` 的 choice。

### 5.2 `POST /v1/completions`

| 输入 | 说明 |
|------|------|
| `prompt` | 字符串或字符串数组；空串/空数组 → `400` |
| `max_tokens`、`temperature`、`top_p`、`stop`、`seed`、`stream`、`n`、`echo` | 映射 |
| `logprobs`、`best_of`、`suffix` | 不支持 → `400` |

输出：`text_completion` / SSE 文本增量。choice 数 = prompts × `n`。

### 5.3 `POST /v1/responses`

| 输入 | 说明 |
|------|------|
| `input` | 字符串或 item 数组 |
| items | `message`（`input_text`/`output_text`/`text`、`input_image`、`input_file`）、`function_call`、`function_call_output`、`reasoning` |
| `input_file` | 支持 `file_data`（base64 或内联 UTF-8）；`file_id` → `501` |
| `instructions` | System message |
| `max_output_tokens`、`temperature`、`top_p` | 映射 |
| `tools`、`tool_choice` | 仅 function 工具；其他类型 → `400` |
| `previous_response_id` | 回放存储的会话；未知 → `400` |
| `metadata`、`store` | 内存存储；`store:false` 不可检索 |
| `text.format` | 映射为 extras 中的 `response_format` |
| `reasoning`、`truncation`、`parallel_tool_calls` | 通过 extras 透传 |
| `background` | 异步执行；与 `stream` 同用 → `400` |

输出：`response` 对象，含 `status`（`completed`/`incomplete`）、`output`
（`reasoning`/`message`/`function_call`）、`output_text`、`usage`。流式事件：
`response.created`、`in_progress`、output item/content part add/done、
`output_text.delta/done`、reasoning delta、`function_call_arguments.done`、
`response.completed`/`failed`。

| 附加端点 | 输出 |
|----------|------|
| `GET /v1/responses/{id}` | 存储的 response，或 `404` |
| `DELETE /v1/responses/{id}` | `{id, object:"response.deleted", deleted:true}` |
| `POST /v1/responses/{id}/cancel` | 取消运行中的 background response；已完成/不存在 → `400`/`404` |

`finish_reason == "length"` 时状态为 `incomplete`。

### 5.4 `POST /v1/embeddings`

输入：`input`（字符串 / 字符串数组 / token 数组 / token 数组的数组）、`dimensions`、
`encoding_format`（`float` 或 `base64`，小端 float32）。输出：`list`，含
`data[{object:"embedding", embedding, index}]`、`model`、`usage`。engine 返回数量不一致
→ `500`；声明 embeddings 能力但没有 `embed` 会使启动失败，运行期方法消失时防御性
返回 `501`。

### 5.5 `POST /v1/moderations`

输入：`input`（字符串/字符串数组）。输出：`id`、`model`、`results[]`、`usage`。

### 5.6 音频

| 端点 | 输入 | 输出 |
|------|------|------|
| `POST /v1/audio/transcriptions` | multipart `file`（必填）、`model`、`language`、`prompt`、`response_format`（`json`/`text`/`srt`/`vtt`/`verbose_json`）、`temperature`、`timestamp_granularities[]` | JSON/文本/字幕；`verbose_json` 含 `task:"transcribe"`、segments、words |
| `POST /v1/audio/translations` | 同上 | 同上，`verbose_json` 的 `task` 为 `"translate"` |
| `POST /v1/audio/speech` | JSON `input`（必填）、`model`、`voice`、`response_format`（mp3/opus/aac/flac/wav/pcm）、`speed`、`instructions` | 音频字节 + media type |

### 5.7 图像

| 端点 | 输入 | 输出 |
|------|------|------|
| `POST /v1/images/generations` | JSON `prompt`（必填）、`model`、`n`、`size`、`quality`、`style`、`response_format` | `{created, data:[{url|b64_json, revised_prompt?}], usage}` |
| `POST /v1/images/edits` | multipart `image`（必填）、`mask`、`prompt`（必填）及公共字段 | 同上 |
| `POST /v1/images/variations` | multipart `image`（必填）及公共字段 | 同上 |

`url` 输出为 `data:image/...;base64,...` URI。

### 5.8 视频

| 端点 | 输入 | 输出 |
|------|------|------|
| `POST /v1/videos` | JSON 或 multipart：`prompt`、`model`、`seconds`、`size`、可选 `input_reference` | job `{id, object:"video", status, created_at, ...}` |
| `GET /v1/videos` | `limit` 1–100（默认 20） | `{object:"list", data:[job], has_more}` |
| `GET /v1/videos/{id}` | — | job 或 `404` |
| `GET /v1/videos/{id}/content` | — | `video/mp4` 字节 |
| `DELETE /v1/videos/{id}` | — | `{id, object:"video.deleted", deleted:bool}` |

### 5.9 `WS /v1/realtime`

若 bundle 实现 `realtime_session(websocket, model)`，由它负责完整事件协议；host 只负责
接受连接、选模型、能力门控和错误转发。

未提供 handler 时，host 提供文本状态机：

| 方向 | 事件 |
|------|------|
| 客户端 → 服务端 | `session.update`、`conversation.item.create/delete/truncate`、`input_audio_buffer.append/commit/clear`、`response.create`、`response.cancel` |
| 服务端 → 客户端 | `session.created/updated`、`conversation.item.created/deleted/truncated`、`input_audio_buffer.committed/cleared`、`response.created`、`response.output_item.added/done`、`response.content_part.added/done`、`response.output_text.delta/done`、`response.function_call_arguments.done`、`response.done`、`error` |

`session.update` 只接受已知字段（`id`/`object`/`model` 不可改）。`response.create` 可带
`response` 覆盖（`instructions`、`tools`、`tool_choice`、`temperature`、
`max_output_tokens`）。音频 `append` 会缓冲；`commit` 生成输入 item，并在 engine 支持
`transcribe` 时自动转写。

### 5.10 模型

Engine 模式下 `GET /v1/models` 与 `GET /v1/models/{id}` 始终可用。默认返回 OpenAI 结构；
当带 `anthropic-version` 且声明 `anthropic.models` 时返回 Anthropic 结构。未知 id → `404`
（`model_not_found` / `not_found_error`）。

## 6. Anthropic 对接（engine 模式）

### 6.1 `POST /v1/messages`

| 输入 | 说明 |
|------|------|
| `messages` | 必填非空 |
| blocks | `text`（保留 `cache_control`）、`image`（base64/url，保留 `cache_control`）、`tool_use`、`tool_result`（文本/图片/`is_error`/`cache_control`）、`thinking`/`redacted_thinking`、`document` |
| `system` | 字符串或 blocks；保留 `cache_control` |
| `max_tokens`、`temperature`、`top_p`、`top_k`、`stop_sequences` | 映射 |
| `stream` | SSE |
| `tools` | `{name, description, input_schema}` → OpenAI function |
| `tool_choice` | `auto`→`auto`、`any`→`required`、`none`→`none`、`tool`→function 对象 |
| `thinking` | extras 中写入 `anthropic_thinking`；`enable_thinking` 由 `type != "disabled"` 推导 |
| `metadata` 等 | extras |

输出（非流式）：`message`，`content` 为 `thinking`/`text`/`tool_use` 块，`stop_reason`
（`end_turn`、`max_tokens`、`tool_use`、`stop_sequence`、`refusal`）、
`usage{input_tokens, output_tokens}`。

输出（流式）：SSE `message_start`、`content_block_start`、`content_block_delta`
（`thinking_delta`/`text_delta`/`input_json_delta`）、`content_block_stop`、
`message_delta`、`message_stop`、`error`。

`tool_result` 中的图片保留为 image part；`cache_control` 在 system、text、image、
tool_result part 上保留。

### 6.2 `POST /v1/messages/count_tokens`

与 messages 相同的校验。输出 `{input_tokens:int}`。声明 `anthropic.count_tokens`
能力但没有 `count_tokens` 会使启动失败；计数异常 → `500`，运行期方法消失时防御性
返回 `501`。

### 6.3 模型

`GET /v1/models` 支持 `limit`（1–1000）与 `before_id`/`after_id`；单模型 host 对任何
游标返回空页。`GET /v1/models/{id}` 在带 `anthropic-version` 时返回 Anthropic 结构。

## 7. 通用转换规则（engine 模式）

| 区域 | 规则 |
|------|------|
| `extras` | `tool_choice`、`response_format`、penalty、`user`、Responses 控制字段、Anthropic thinking 参数透传给 bundle |
| `tool_choice` | Anthropic 归一化为 OpenAI 形式 |
| 多模态 | Anthropic image block → image URL part；tool_result 图片保留 |
| 推理 | 结果用 `reasoning_content`；输出为 `thinking` 块 / `reasoning` item |
| `n > 1` | chat 与 completions 的流式/非流式均支持；usage 合并 |
| Usage | chat/responses 由 engine usage 推导；缺失字段默认 0 |
| Busy | 由 `serve.concurrency` 决定的推理槽位；`503` + `Retry-After: 5` |

## 8. 兼容与门控（engine 模式）

- 无 `serve.capabilities` 的旧 manifest 仅保留 `openai.chat`。
- `[]` 仅保留 health/models，无推理路由。
- `register_routes` 自定义端点不受门控影响。
- 未知能力 ID 校验失败。
- Script 与 native serve 不使用该门控模型，由自身实现端点。

## 9. 校验与验收（engine 模式）

```bash
flashcli bundle validate <bundle-or-dist>
pytest tests/test_serve_protocol_matrix.py tests/test_serve_realtime.py tests/test_serve_concurrency.py

# 真实 bundle 验收：生成 llm/code/anthropic/asr/tts/audio/image/video/legacy 测试 bundle，
# 通过 flashcli-bundle.infer serve 启动并做真实 socket 请求。
FLASHCLI_ACCEPTANCE=1 pytest tests/acceptance/test_serve_bundles.py
```

`flashcli bundle validate` 只做静态 manifest/文件检查：能力 ID、重复项、并发值、
entry 模块文件是否存在。若有可用的 Python 解释器（不需要 venv），还会对直接定义的
`ServeEngine` 类做 best-effort AST 方法检查；`concurrency > 1` 时同时检查受门控方法
是否为异步。导入/继承/动态类以及没有 Python 的环境会跳过该检查；`flashcli serve` 与
`flashserver` 的加载检查仍是权威。直接可见的类缺少声明能力的方法时 `bundle validate`
会失败；无论如何，serve 启动都会再次强制检查。

发布前用发布树执行 `flashcli serve`，至少验证非流式 + 流式 chat、工具与 `tool_choice`、
Anthropic messages 与流式事件、`count_tokens`，以及所有已声明的非 chat 能力。

## 10. 已知限制

以下限制针对 **engine 模式的 host 协议面**；script/native serve 可在 bundle 内自行实现。

| 区域 | 限制 |
|------|------|
| Chat | `logprobs`/`response_format` 仅透传，不生成/不强制 |
| Completions | `logprobs`/`best_of`/`suffix` 被拒绝 |
| Responses | 不支持 `file_id`/非文本文件；无 input_items/input_tokens/include；无内置工具；background 仅内存 |
| Audio | 无流式转写/分块；speech 无流式 |
| Images | 无 stream/background/output format 控制 |
| Videos | 无 remix 或游标分页 |
| Realtime | 文本状态机；无 TTS/VAD/音频输出；reasoning 不输出 |
| Anthropic | 无 batches/files/MCP/container/context_management/output_config；`disable_parallel_tool_use` 丢弃 |
| 平台 API | OpenAI Batch/Files/Fine-tuning/Assistants/Vector Stores 范围外 |
| 鉴权/限流 | 本地单用户 CLI，故意不实现 |
| Serve 形式 | `native-exec` stdio 与 `native-abi` 的 serve 尚未实现 |
| 并发 | `serve.concurrency > 1` 要求受门控方法为异步；同步受门控方法会被拒绝 |

## 相关文档

- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) —— manifest、目录、发布
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) —— entry kind 与 native serve 行为
- [module_layers.zh-CN.md](module_layers.zh-CN.md) —— host/infer/protocol 归属
- [bundle_builder_guide.zh-CN.md](bundle_builder_guide.zh-CN.md) —— 构建与发布
