# 音频分离 Bundle 分类规范（`POST /v1/audio/separations`）

<p align="right"><a href="bundle_audio_separation_standard.md">English</a> · <strong>简体中文</strong></p>

> **分类补充规范。** 通用 manifest、目录布局、entry、运行时、权重与发布规则仍以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)（英文版：[bundle_publish_standard.md](bundle_publish_standard.md)）为准。本页只补充音频分离服务特有的要求，不重复这些规则。
>
> **由宿主负责的服务行为。** engine 模式下标准路由、鉴权、推理槽位并发、请求日志、SSE 传输与协议错误转换均由宿主负责，定义见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)（英文版：[bundle_serve_protocols.md](bundle_serve_protocols.md)）。本页不重新定义这些行为。
>
> **网关模型选择。** 直连 `flashcli serve` 时一个部署就是一个模型，因此请求不带 `model` 字段。多模型 flashserver `/v1` 网关对自定义路径使用查询选择器：`POST /v1/audio/separations?model=<namespace/name:version>`。网关解析常驻模型后**在转发前移除该查询参数**，路径与请求体原样转发。请求体契约不会新增 `model` 字段，响应中也不包含该字段。

本规范定义音频分离 bundle 的调用契约：将输入录音分离为**对话人声**（`voice`）与**其他所有声音**（`ambience`）的模型。内容覆盖 `POST /v1/audio/separations` 的线格式、音轨语义、响应/错误结构、执行要求与安全限制。

```bash
# 直连部署（一个端点一个模型）
flashcli serve <org>/<name>:<version> --host 0.0.0.0 --port 8080
#   POST http://<host>:8080/v1/audio/separations

# 多模型网关（自定义路径必须携带选择器）
#   POST http://<gateway>/v1/audio/separations?model=<org>/<name>:<version>
```

---

## 1. 适用范围与定位

| 项目 | 取值 |
|---|---|
| API 版本 | `v1` |
| 端点 | `POST /v1/audio/separations` |
| 风格 | OpenAI 兼容 REST API，含本地运行扩展 |
| 执行方式 | 仅同步 |
| 输入 | `wav`、`mp3` —— 文件上传、URL 或服务端本地路径 |
| 输出 | `wav`、`mp3`，写入服务端本地目录 |
| 结果 | JSON，返回音轨的服务端本地路径 |

- 一个 bundle 代表**一个分离模型**，调用方不在请求体中选择模型。鼓、贝斯、吉他、钢琴等乐器级分离不属于本版本范围。
- API 仅在**风格上**与 OpenAI 对齐（资源命名、JSON 参数、error 对象），OpenAI 并没有原生音频分离端点；该路径及其字段属于本地扩展，不代表 OpenAI 官方支持。
- 模型 MUST 提供 §3 定义的语义。仅把通用“人声/伴奏”分离器的输出改名**不构成**符合规范；能力不足时服务必须报告（§7）。
- 执行是同步的。v1 不定义流式响应，也不定义异步任务或状态轮询。响应中的 `id` 仅标识本次请求，不是任务 ID。
- 音频分离 bundle 统一以 **engine 模式**打包，并把该路由作为自定义路由提供。宿主通过 `register_routes(app)` 挂载自定义路由，且其优先级高于宿主路由；标准路由仍由宿主提供。该路由不是宿主能力，因此不在宿主的推理闸门内：bundle MUST 自行校验请求、串行化 GPU 调用并实施自身限制，同时遵循 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) 描述的宿主鉴权与日志行为。

---

## 2. 端点

| 项目 | 定义 |
|---|---|
| HTTP 方法 | `POST` |
| 端点 | `/v1/audio/separations` |
| `Content-Type` | `multipart/form-data` 或 `application/json` |
| `Accept` | `application/json` |
| 执行 | 同步 |
| 响应 | JSON（`application/json`） |

两种请求编码共用同一端点；输入来源决定编码方式（§4.2、§5）。

---

## 3. 音轨类型

仅定义两种音轨类型，不细分乐器。

| Stem | 名称 | 定义 |
|---|---|---|
| `voice` | 对话人声 | 仅包含人类说话：对话、旁白、采访等语音内容。MUST NOT 包含歌曲演唱、主唱或和声。 |
| `ambience` | 其他声音 | 除对话人声以外的所有声音：背景音乐、歌曲演唱、和声、鼓、贝斯、吉他、钢琴、环境声、机械声、动物声及其他非对话音频。 |

### 3.1 选择与默认行为

- 不传 `stems` 时，同时生成 `voice` 与 `ambience`，顺序即此顺序。
- 传入 `stems` 时，只生成请求指定的类型，并按请求顺序返回。
- 只请求 `voice` 时仅输出对话人声；只请求 `ambience` 时输出其余全部声音。
- 模型 MUST 支持请求中的每一种音轨类型。未知取值返回 `400 unsupported_stem`；类型已定义但模型无能力生成时返回 `400 unsupported_separation_capability`。
- `ambience` 是通用的“剩余音频”类别，不代表“仅环境氛围声”。

### 3.2 输出语义

- `voice` 与 `ambience` MUST 是**同一输入**的两个分离结果。
- 音轨 MUST 尽可能保持原始时间轴：起始位置、时长、采样率、声道数以及音轨间的同步关系。
- `voice` MUST NOT 包含歌曲演唱、主唱或和声；`ambience` MUST 包含其余全部声音，且 MUST NOT 对具体乐器分类。
- 只返回确实已生成的请求音轨；部分成功时 MUST NOT 声明 `status: "completed"`。

### 3.3 模型能力

- 模型 MUST 具备区分对话语音与其他声音的能力。
- 只能做“人声（说话与演唱）对伴奏”分离的模型，在能够排除演唱与音乐人声之前不满足 `voice` 语义。此时服务 MUST 返回 `unsupported_separation_capability`，不得返回语义错误的音轨。
- 能力 MUST 在请求时校验。禁止静默降级为语义不同的输出。

---

## 4. 请求

`POST /v1/audio/separations`，使用 `multipart/form-data` 或 `application/json`。JSON 请求体是一个 JSON 对象。

### 4.1 公共参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `stems` | array[string] | 否 | `["voice","ambience"]` | 需要生成的音轨类型 |
| `prompt` | string | 否 | `""` | 文本提示，仅对支持提示分离的模型生效 |
| `output_format` | string | 否 | `wav` | 输出编码：`wav` 或 `mp3` |
| `output_directory` | string | 是 | — | 服务端本地输出目录 |

`prompt` 规则：

- 默认值为空字符串，表示不使用提示。
- 支持提示分离的模型 SHOULD 按提示执行（例如指定保留或去除哪类声音）。
- 不支持提示的模型 MUST 忽略 `prompt`，且 MUST NOT 因传入该参数而报错。
- `prompt` 不改变 §3 的音轨语义；`stems` 始终是权威定义。

multipart 请求中除文件外的字段都是字符串：`stems` 为 JSON 数组字符串（例如 `["voice","ambience"]`），`output_format` / `output_directory` 为普通字符串。

### 4.2 输入来源：三选一

| 参数 | 类型 | 编码 | 说明 |
|---|---|---|---|
| `file` | file | `multipart/form-data` | 上传的音频文件 |
| `audio_url` | string | `application/json` | 由服务端下载的音频 URL |
| `audio_path` | string | `application/json` | 服务端本地音频文件路径 |

- 请求 MUST 且只能提供 `file`、`audio_url`、`audio_path` 中的**一个**。未提供或提供多个时返回 `400 invalid_input`，并在 `param` 中指明问题字段。
- 服务 MUST NOT 接受同时混用上传文件与 URL/路径来源的请求。
- `audio_path` 在运行模型进程的机器上解析，而不是在客户端解析。服务 MUST 将其限制在已授权的可读目录内；文件不存在或不可读时返回 `404 file_not_found`。
- `audio_url` 由服务端下载。协议、目标地址与重定向按 §9 限制。

### 4.3 模型选择

请求体中没有 `model` 字段。模型选择取决于前端：

| 前端 | 选择方式 |
|---|---|
| 直连 `flashcli serve` | 部署本身就是模型。分离请求没有 `model` 参数，也没有模型协商。 |
| flashserver `/v1` 网关 | 自定义路径必须携带查询选择器 `?model=<namespace/name:version>`，例如 `/v1/audio/separations?model=aodianyun/audio-separator:1.0.0`。网关解析该引用的常驻模型，移除查询参数，并原样转发路径、请求头与请求体。 |

规则：

- 查询选择器是**网关**的职责。bundle MUST 忽略查询字符串，MUST NOT 要求、解析或回显 `model`。
- 不得新增 `model` JSON 字段或 multipart 字段。两种前端下的请求体契约完全一致。
- 响应中永远不包含 `model` 字段；直连时由端点标识模型，网关时由解析出的目标标识模型。
- 该选择器同样适用于 JSON 与 multipart 请求；它属于 URL，不属于负载。
- 缺少或无法解析选择器时，网关在转发前拒绝请求；这不属于音频分离错误，也不会到达 bundle。

### 4.4 音频格式要求

| 格式 | 输入 | 输出 |
|---|---|---|
| WAV | 支持 | 支持 |
| MP3 | 支持 | 支持 |

- 不支持视频输入；调用方需先提取音频。
- 文件扩展名 MUST 与实际音频编码一致。
- 服务端负责必要的解码、重采样与编码。
- `output_format` 默认为 `wav`；`mp3` 输出需要 MP3 编码器。不强制依赖 FFmpeg，可使用其他合适的编解码库。

---

## 5. 请求示例

### 5.1 直接上传文件

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -F "file=@input.wav" \
  -F 'stems=["voice","ambience"]' \
  -F "prompt=" \
  -F "output_format=wav" \
  -F "output_directory=/data/output/"
```

MP3 输入，并使用 `stems` 与 `prompt` 的默认值：

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -F "file=@input.mp3" \
  -F "output_format=mp3" \
  -F "output_directory=/data/output/"
```

### 5.2 URL 输入

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://example.com/input.wav",
    "stems": ["voice", "ambience"],
    "prompt": "保留所有对话人声",
    "output_format": "wav",
    "output_directory": "/data/output/"
  }'
```

服务端下载该音频并执行分离。`prompt` 可省略，省略时按空字符串处理。

### 5.3 服务端本地路径输入

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_path": "/data/input/input.wav",
    "stems": ["voice", "ambience"],
    "output_format": "mp3",
    "output_directory": "/data/output/"
  }'
```

`audio_path` 与 `output_directory` 都是服务端本地路径。当客户端与服务端共享文件系统时，两侧可以使用同一路径；本地已有的文件无需再通过 HTTP 上传。

### 5.4 通过网关调用

```bash
curl -X POST "http://gateway:8790/v1/audio/separations?model=aodianyun/audio-separator:1.0.0" \
  -H "Content-Type: application/json" \
  -d '{"audio_path": "/data/input/input.wav", "output_directory": "/data/output/"}'
```

网关会移除 `?model=...`；bundle 收到的请求体与 §5.3 相同。

---

## 6. 响应

成功请求返回 `200 OK` 与 `application/json`。

### 6.1 成功返回（WAV）

```json
{
  "id": "sep_123456",
  "object": "audio.separation",
  "status": "completed",
  "input": {
    "filename": "input.wav",
    "format": "wav",
    "duration": 120.5
  },
  "output": {
    "format": "wav",
    "directory": "/data/output/",
    "stems": [
      {
        "type": "voice",
        "format": "wav",
        "path": "/data/output/voice.wav"
      },
      {
        "type": "ambience",
        "format": "wav",
        "path": "/data/output/ambience.wav"
      }
    ]
  }
}
```

### 6.2 MP3 输出

```json
{
  "id": "sep_123457",
  "object": "audio.separation",
  "status": "completed",
  "input": {
    "filename": "input.mp3",
    "format": "mp3",
    "duration": 120.5
  },
  "output": {
    "format": "mp3",
    "directory": "/data/output/",
    "stems": [
      {
        "type": "voice",
        "format": "mp3",
        "path": "/data/output/voice.mp3"
      },
      {
        "type": "ambience",
        "format": "mp3",
        "path": "/data/output/ambience.mp3"
      }
    ]
  }
}
```

### 6.3 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 本次请求的唯一标识 |
| `object` | string | 固定为 `audio.separation` |
| `status` | string | 同步执行成功后为 `completed` |
| `input` | object | 输入音频信息 |
| `input.filename` | string | 输入文件名 |
| `input.format` | string | 输入音频格式 |
| `input.duration` | number | 音频时长，单位秒 |
| `output` | object | 输出信息 |
| `output.format` | string | 输出音频格式 |
| `output.directory` | string | 输出目录 |
| `output.stems` | array | 已生成的音轨列表 |
| `output.stems[].type` | string | `voice` 或 `ambience` |
| `output.stems[].format` | string | 音轨文件格式 |
| `output.stems[].path` | string | 音轨文件的服务端本地路径 |

### 6.4 响应语义

- `id` 仅标识本次请求，不是异步任务 ID。
- `output.stems` 只包含请求过**且**成功生成的音轨。
- 所有返回路径都是服务端本地路径。位于另一台机器的客户端需要共享挂载才能读取；v1 不定义下载端点。
- `voice` 与 `ambience` 是同一输入的两个分离结果，MUST 保持相互时间对齐。
- 响应中永远不包含 `model`；模型由部署端点或网关解析出的目标标识。
- 请求失败或仅部分成功时，`status` MUST NOT 为 `completed`（§7）。

---

## 7. 错误返回

错误使用 JSON 与 OpenAI 风格的 error 对象：

```json
{
  "error": {
    "message": "Exactly one input source must be provided.",
    "type": "invalid_request_error",
    "param": "audio_path",
    "code": "invalid_input"
  }
}
```

| HTTP | `code` | `param` | 场景 |
|---|---|---|---|
| 400 | `invalid_input` | 问题来源字段 | 未提供输入来源，或 `file` / `audio_url` / `audio_path` 提供多个 |
| 400 | `unsupported_audio_format` | `file` / `audio_url` / `audio_path` | 输入不是 WAV/MP3，或无法按声明格式解码 |
| 400 | `unsupported_stem` | `stems` | 请求的音轨不是 `voice` / `ambience` |
| 400 | `unsupported_separation_capability` | — | 模型无法满足请求的音轨语义（例如无法排除演唱） |
| 404 | `file_not_found` | `audio_path` | 服务端本地输入文件不存在或不可读 |
| 500 | `separation_failed` | — | 推理或输出编码失败 |

规则：

- `message` 为人类可读信息；4xx 的 `type` 为 `invalid_request_error`，5xx 为 `server_error`。
- `param` 指明问题字段；没有单一字段可归因时省略。
- 失败的请求 MUST NOT 返回 `status: "completed"`，也不得为未生成的音轨返回路径。
- 该路由由 bundle 自身提供，因此由 bundle 负责按本结构输出错误；宿主的协议错误转换只覆盖宿主挂载的路由。

---

## 8. 服务端执行要求

执行顺序：

1. 接收请求，校验输入来源、音频格式与音轨类型。
2. 校验模型是否具备请求的分离能力；若请求携带非空 `prompt` 且模型支持提示，则按提示执行。
3. 读取上传文件、服务端本地文件或已下载的 URL 内容。
4. 按需解码并预处理音频。
5. 执行分离。
6. 获取 `voice` 与 `ambience` 对应的 PCM 波形。
7. 将波形编码为请求的格式（`wav` 或 `mp3`）。
8. 将音轨文件写入 `output_directory`。
9. 返回包含生成路径的 JSON 结果。

其他要求：

- `output_directory` 不存在时可以自动创建。
- 同步请求 MUST 等待所有请求的音轨写入完成后再返回成功。
- 不同请求的输出文件 MUST NOT 相互覆盖；建议为每个请求使用唯一子目录。
- 音频分离受 GPU 约束：bundle SHOULD 在单设备上一次只执行一个推理。自定义路由不在宿主推理闸门内，因此串行化由 bundle 负责。
- `voice` MUST NOT 包含演唱或和声；`ambience` MUST 包含其余全部声音，且不做乐器级分类。
- 模型无法满足“对话语音与演唱”区分要求时，必须报告 `unsupported_separation_capability`；不得静默降级并返回语义错误的音轨。
- 模型不支持 `prompt` 时忽略该参数，不得因此返回参数错误。

---

## 9. 安全与限制

- **本地路径。** `audio_path` 只能访问服务已授权的可读目录。`output_directory` 必须是可写的服务端本地目录；实现 SHOULD 将二者分别限制在配置的输入根与输出根内。
- **URL。** 下载 MUST 仅允许 `http`/`https`，限制目标端口，默认阻断回环/私有/链路本地地址，限制重定向次数并对每一跳重新校验。以此防止访问内网服务（SSRF）。
- **大小与时长。** 实现 MUST 限制上传大小、解码后的音频时长与处理时间；超过限制时 MUST 按 §7 结构返回客户端错误（v1 不为该场景固定专用 `code`）。
- **输出冲突。** MUST 使用按请求划分的子目录（或等效的唯一命名），避免并发请求互相覆盖音轨。
- **路径穿越。** 处理音轨路径与 `output_directory` 时 MUST NOT 允许逃逸出授权根目录。
- 服务 SHOULD 避免记录音频内容；请求日志由宿主负责（见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)），且不得附加负载转储。

---

## 10. 当前版本支持范围

| 能力 | v1 |
|---|---|
| WAV 输入 | 支持 |
| MP3 输入 | 支持 |
| WAV 输出 | 支持 |
| MP3 输出 | 支持 |
| 文件上传 | 支持 |
| URL 输入 | 支持 |
| 服务端本地路径输入 | 支持 |
| 服务端本地路径输出 | 支持 |
| 对话人声音轨 `voice` | 支持，取决于模型能力 |
| 剩余声音音轨 `ambience` | 支持，取决于模型能力 |
| 默认输出两条音轨 | 支持 |
| `prompt` 提示 | 模型具备提示分离能力时支持，否则忽略 |
| 请求 `model` 字段 | 不提供（由部署的 bundle 或网关选择器决定模型） |
| 同步执行 | 支持 |
| 流式执行 | 不支持 |
| 异步任务/状态轮询 | 不支持 |
| 视频输入/音轨提取 | 不支持 |
| 乐器音轨（鼓、贝斯、吉他、钢琴） | 不属于本版本范围 |

---

## 11. 一致性检查清单

- [ ] `POST /v1/audio/separations` 同时接受 `multipart/form-data` 与 `application/json`。
- [ ] 强制 `file` / `audio_url` / `audio_path` 三选一；违规返回 `400 invalid_input` 并给出问题 `param`。
- [ ] `stems` 默认 `["voice","ambience"]`，支持子集，并按请求顺序返回。
- [ ] 演唱、主唱与和声不会出现在 `voice` 中；`ambience` 承载其余全部声音。
- [ ] 模型不具备所需区分能力时返回 `400 unsupported_separation_capability`，而不是错误的音轨。
- [ ] 模型不支持 `prompt` 时忽略且不报错；`prompt` 不改变音轨语义。
- [ ] `output_format` 支持 `wav` 与 `mp3`，默认 `wav`，并与 `output.format` / 音轨 `format` 一致。
- [ ] 正确使用 `output_directory`，可按需创建，并发请求不会互相覆盖。
- [ ] 成功响应与 §6 完全一致，只包含已生成的音轨，并使用服务端本地路径。
- [ ] 错误符合 §7：HTTP 状态码、`code`、`param` 与 `type`。
- [ ] 执行是同步的：没有流式、没有异步任务 ID，成功返回前等待全部请求音轨。
- [ ] 本地路径受限，URL 抓取具备 SSRF 防护，大小/时长/超时限制生效。
- [ ] 在 flashserver 网关上，`?model=` 被移除后服务工作正常；请求体与响应中均无 `model` 字段。
- [ ] 发布目录通过 `flashcli bundle validate`，并通过 `flashcli serve` 完成上述检查。

---

## 相关文档

- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) — manifest、目录、权重、运行时与发布
- [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) — 宿主负责的 engine 模式服务面
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) — `entry.kind` 与 script/engine/native 后端
