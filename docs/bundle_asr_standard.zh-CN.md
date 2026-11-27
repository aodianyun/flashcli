# ASR Bundle 服务规范（OpenAI 兼容 API）

<p align="right"><a href="bundle_asr_standard.md">English</a> · <strong>简体中文</strong></p>

面向本地部署的开源 ASR 模型，定义一套**以 OpenAI `/v1/audio/transcriptions` 为形状**、但能诚实表达模型差异的调用契约。

本规范适用于任意本地 ASR 模型；文中 `qwen3-asr-1.7b`、`moss-transcribe-diarize` 仅作为声明示例，不构成适用范围限制。

---


> **分类补充规范。** 通用 manifest、目录、权重、运行时和发布规则仍以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) 为准；engine 模式的 host 行为（`/health`、`/v1/models`、鉴权、并发、请求日志、SSE 传输、错误转换）见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)；本文只补充 ASR 专有路由、schema、限制和验收。
>
> **FlashCLI 集成方式。** 新 ASR bundle 使用 `format_version: 4`，可采用以下任一形式：
>
> - **engine 模式**：实现 `ServeEngine.transcribe` 处理 `/v1/audio/transcriptions` / `translations`，并用 `register_routes(app)` 注册 `/v1/audio/spec`；`/health` 由 host 持有；
> - **script 模式**：由 bundle 自己启动 HTTP 服务，完整实现下面的契约。
>
> 在 `entry.serve.capabilities` 中声明 `openai.audio.transcriptions`（支持翻译时再加 `openai.audio.translations`）。
>
> **网关透传。** flashserver `/v1` 网关会代理 `/v1/audio/transcriptions` / `translations`，并把 `/v1/audio/spec` 等自定义路径透传到模型 serve 端点。额外的 multipart 字段会被转发，但模型必须能容忍。按模型声明的 `parameters` / `limits` 位于 `/v1/audio/spec.models[]`；`/v1/models` 仍是网关的标准模型列表。

## 0. 规范定位

本规范是**契约**，不是实现指南。

- 实现者可按本规范构建兼容多个 ASR 模型的 API 网关，或为单个 ASR 模型提供 OpenAI 兼容的 `/v1/audio/transcriptions` 支持。
- 实现可自由选择内部结构、模型加载方式、推理后端与部署形态，只要遵循本规范即可。
- 本文只规定线格式、能力声明与行为契约；模型加载、推理后端、部署形态等实现细节不属规范正文（单模型部署建议见 §11）。

---

## 1. 设计原则

**P1 三层分离。** 协议分三层，互不越界：

| 层 | 内容 | 变更成本 |
|---|---|---|
| L1 线格式 | 路径、multipart 字段、响应形状 | 高（客户端依赖） |
| L2 参数与限制 | `parameters`（逐参数支持与处理）与 `limits`（资源硬边界） | 中（随模型增加） |
| L3 扩展命名空间 | `x_gateway` 下的厂商私有数据 | 低（自由增删） |

**P2 可观测降级。** 做不到的参数，MUST 二选一：拒绝并说明，或降级并在 `degraded` 里逐条报告。**禁止静默忽略。**

**P3 不伪造数据。** 没有词级时间戳就不输出 `words`；没有说话人就不输出 `speaker`。宁可 `null`，不可猜测。

**P4 一个内部结果，三类 OpenAI 响应。** `response_format` 只改变呈现；`json` / `verbose_json` / `diarized_json` 分别渲染为 OpenAI 的 `Transcription` / `TranscriptionVerbose` / `TranscriptionDiarized`，不改变信息模型。

**P5 声明与策略合一。** 每个模型在 `/v1/audio/spec.models[]` 中自描述：`description`（可选、人类可读）、`parameters`（必填，逐 OpenAI 参数声明支持情况与不支持时的处理）、`limits`（与参数形状无关的资源硬边界）。客户端读取一份声明即可判断行为。

---

## 2. 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/audio/transcriptions` | 转写，`multipart/form-data` |
| GET | `/v1/models` | 标准 OpenAI 模型列表（host 持有，不是 bundle 注册表） |
| GET | `/v1/audio/spec` | 规范版本与模型声明注册表（`models[]`） |
| GET | `/health` | 存活探针（engine 模式由 host 持有；script 模式可用 `/healthz`） |

`GET /v1/audio/spec` 返回规范版本和模型声明注册表：

```json
{
  "spec_version": "2026-11-26",
  "models": [
    {
      "id": "moss-transcribe-diarize",
      "object": "model",
      "description": "…",
      "parameters": { "…": "…" },
      "limits": { "…": "…" },
      "extensions": { "…": "…" }
    }
  ]
}
```

---

## 3. 请求

`POST /v1/audio/transcriptions`，`Content-Type: multipart/form-data`。

数组参数在 multipart 中以**带方括号的重复字段**出现（`languages[]`、`keywords[]`、`timestamp_granularities[]`、`known_speaker_names[]`、`known_speaker_references[]`、`include[]`）；这与 openai-python 的编码方式一致。

| 字段 | 必需 | 默认 | 约定 |
|---|---|---|---|
| `file` | MUST | — | 音频文件。网关不要求客户端预转码；解码由模型侧负责；格式须在模型的 `limits.formats` 内 |
| `model` | MUST | — | 必须匹配部署模型 id；经 flashserver 代理时网关发送完整 bundle ref，引擎可自行归一化。不支持别名 |
| `language` | MAY | `auto` | 单个语言提示，ISO-639-1（`zh`/`en`/`yue`） |
| `languages[]` | MAY | `[]` | 本次音频**可能**包含的语言集合，ISO-639-1；与 `language` 可共存；模型不支持集合时按 §6 降级 |
| `prompt` | MAY | `""` | **术语/上下文提示**，不是指令（见 §3.2） |
| `response_format` | MAY | `json` | `json` / `text` / `srt` / `verbose_json` / `vtt` / `diarized_json` |
| `temperature` | MAY | `0` | 非 0 且模型确定性解码时降级（见 §6） |
| `timestamp_granularities[]` | MAY | `[]` | `word` / `segment`；显式请求模型不具备的粒度时拒绝（见 §6） |
| `stream` | MAY | `false` | 本规范不定义流式响应；模型不支持时 422 |
| `include[]` | MAY | `[]` | 额外返回信息，目前仅 `logprobs`；不支持时降级 |
| `keywords[]` | MAY | `[]` | 热词/术语引导；模型无独立通道时由网关转换（如拼进转写指令的“热词提示”） |
| `known_speaker_names[]` | MAY | `[]` | 已登记说话人名称，数量受 `parameters.known_speaker_names.max_items` 约束（见 §3.4） |
| `known_speaker_references[]` | MAY | `[]` | 与名称按顺序对应的参考音频，data URL，每段 2–10 秒（见 §3.4） |
| `chunking_strategy` | MAY | `auto` | `auto` / `vad` / `fixed` / `none`；是否支持及处理方式由模型声明（见 §8） |
| `strict` | MAY | `false` | 本规范扩展，见 §6 |

### 3.1 时间

- 单位统一为**秒**，`float`，保留 3 位小数（毫秒精度）。
- `segments` MUST 单调不减；MUST 落在 `[0, duration]` 内。

### 3.2 `prompt` 的语义重定义

同一个字段，Whisper 系是“上文延续”，生成式模型是“指令”。直接透传会得到不稳定输出（模型可能开始总结或解释）。

规范：

- `prompt` MUST 只承载术语表、专有名词、上下文片段。
- 网关负责转译：Whisper 系 → decoder prefix；生成式模型 → 拼接进转写指令；不支持 prompt 的模型 → 忽略并记入 `degraded`。
- 任何模型都 MUST NOT 因 `prompt` 而输出解释性文字、标题、Markdown。

### 3.3 语言

- 对外只用 ISO-639-1；`null` 表示“未检测/未报告”，不是 `"unknown"`。
- 出站时，若模型返回的是全名（如 `Chinese`），网关统一转为 ISO-639-1。
- `language` 是单值提示；`languages[]` 是候选集合，二者语义不同、可共存。
- `language` 的允许值由 `parameters.language.values` 声明；不在其中时按该参数的 `on_unsupported` 处理（例如 `degrade` 表示忽略提示并记录）。
- `languages[]` 若声明为 `support: "unsupported"`，按 `on_unsupported` 处理（例如 `degrade` 表示忽略集合并记入 `degraded`）。

### 3.4 说话人与具名说话人

- 请求说话人分离 MUST 使用 `response_format=diarized_json`。模型不支持说话人时按 §6 拒绝。
- `known_speaker_names[]` 与 `known_speaker_references[]` **按下标一一对应**：每个名称配一个参考音频（data URL，2–10 秒，格式与 `file` 相同）。两者长度 MUST 一致，条数 MUST 在各自的 `min_items` / `max_items` 范围内（OpenAI 为 1–4）；不满足时返回 400。
- 提供具名说话人时，`diarized_json.segments[].speaker` MUST 使用登记的名称；否则使用 `A`/`B`/… 顺序标签。
- 模型不支持说话人具名化时，携带 `known_speaker_*` 的请求按 §6 **拒绝**，不得降级为匿名分离。

### 3.5 自定义参数（OpenAI 之外）

- 自定义参数 MUST 使用 `x_` 前缀，例如 `x_vad_threshold`；数组沿用方括号：`x_<name>[]`。
- 自定义参数 MUST 在 `/v1/audio/spec` 的 `extensions` 中声明；未声明的 `x_*` 字段返回 400。
- `extensions` 的键为逻辑名（不含 `x_` 前缀），并额外声明 `type`（`string` / `number` / `boolean` / `array`）。
- 自定义参数 MUST NOT 与 OpenAI 参数同名，也 MUST NOT 使用 `x_gateway`（保留给响应）。
- 客户端使用 openai-python 时，通过 `extra_body={"x_vad_threshold": 0.5}` 传递；SDK 会编码为平铺字段。

---

## 4. 能力与参数声明

`GET /v1/audio/spec` 的 `models[]` 每项由四部分组成：`description`（可选）、`parameters`（必填）、`limits`（必填）、`extensions`（可选，自定义参数）。

以下为单个模型的声明示例：

```json
{
  "id": "moss-transcribe-diarize",
  "object": "model",
  "description": "MOSS 转写 + 匿名说话人分离；仅句级时间戳。",
  "parameters": {
    "file": { "support": "native" },
    "model": { "support": "native" },
    "language": { "support": "native", "values": ["*"] },
    "languages": { "support": "unsupported", "on_unsupported": "degrade", "max_items": 4 },
    "prompt": { "support": "native" },
    "response_format": {
      "support": "native",
      "values": ["json", "text", "srt", "verbose_json", "vtt", "diarized_json"],
      "on_unsupported": "reject"
    },
    "temperature": {
      "support": "unsupported",
      "on_unsupported": "degrade",
      "values": { "min": 0, "max": 1 }
    },
    "timestamp_granularities": {
      "support": "native",
      "values": ["segment"],
      "max_items": 1,
      "on_unsupported": "reject"
    },
    "stream": { "support": "unsupported", "on_unsupported": "reject" },
    "include": {
      "support": "unsupported",
      "on_unsupported": "degrade",
      "values": ["logprobs"],
      "max_items": 1
    },
    "keywords": {
      "support": "emulated",
      "max_items": 50,
      "note": "拼进转写指令的“热词提示”"
    },
    "known_speaker_names": {
      "support": "unsupported",
      "on_unsupported": "reject",
      "min_items": 1,
      "max_items": 4
    },
    "known_speaker_references": {
      "support": "unsupported",
      "on_unsupported": "reject",
      "min_items": 1,
      "max_items": 4,
      "note": "每项为 2–10 秒音频 data URL，与 known_speaker_names[] 按下标对应"
    },
    "chunking_strategy": {
      "support": "emulated",
      "values": ["auto", "none"],
      "on_unsupported": "reject"
    }
  },
  "limits": {
    "formats": ["wav", "mp3", "m4a", "flac", "ogg", "webm"],
    "max_audio_seconds": 3600
  }
}
```

### 4.1 三部分与字段语义

**`description`（可选）**：人类可读描述，仅供了解模型，不参与校验。

**`parameters`（必填）**：MUST 覆盖完整 OpenAI 参数清单：

`file`、`model`、`language`、`languages`、`prompt`、`response_format`、`temperature`、`timestamp_granularities`、`stream`、`include`、`keywords`、`known_speaker_names`、`known_speaker_references`、`chunking_strategy`。

每项字段：

| 字段 | 取值 | 规则 |
|---|---|---|
| `support` | `native` / `emulated` / `unsupported` | 必填 |
| `values` | 数组 / `"*"` / `{"min":..,"max":..}` | 可选；标量的允许值，或数组元素的允许值；`"*"` 表示不限制 |
| `min_items` / `max_items` | 整数 | 仅数组参数；声明元素数量范围 |
| `on_unsupported` | `reject` / `degrade` | `support=unsupported` 或 `values` 为枚举数组时必填 |
| `note` | 字符串 | 可选的人类可读说明 |

- `values` 为**枚举数组**时：请求值不在其中 → 按 `on_unsupported` 处理（`reject` → 422，`degrade` → 降级并记 `degraded`）。
- `values` 为**数值范围**（`{"min":..,"max":..}`）越界、`min_items` / `max_items` 越界、跨参数不一致、数组格式非法 → 400 `invalid_request_error`。
- `values: "*"` 表示不限制。
- 空数组视为“未提供”，不触发 `min_items`。
- `parameters` 缺任何 OpenAI 参数 → 能力声明非法。
- `known_speaker_names[]` 与 `known_speaker_references[]` 的长度 MUST 一致，否则 400；该跨参数规则由本规范强制，不在声明中表达。

**`limits`（必填）**：只放与 OpenAI 参数形状/数量无关的模型资源硬边界：

| 字段 | 含义 |
|---|---|
| `formats` | 可接受的输入容器 |
| `max_audio_seconds` | 音频时长上限 |
| `max_timestamped_audio_seconds` | 请求时间戳（word 级）时允许的最大音频时长 |
| `max_upload_bytes` | 上传体积上限 |

- 违反 `limits` 一律拒绝（`413` / `400` / `415`），与 `strict` 无关。
- 只列该模型适用的条目。

**`extensions`（可选）**：OpenAI 之外的自定义参数声明，键为逻辑名（线上名为 `x_<name>`），每项额外包含 `type`，其余字段同上：

```json
"extensions": {
  "vad_threshold": {
    "type": "number",
    "support": "native",
    "values": { "min": 0, "max": 1 }
  }
}
```

### 4.2 两个示例模型的声明摘要

以下摘要用于说明同一规范如何映射到不同模型，不构成规范要求；实际能力以各模型 `/v1/audio/spec` 声明为准。

| 参数 | qwen3-asr-1.7b | moss-transcribe-diarize |
|---|---|---|
| `file` / `model` | `native` | `native` |
| `language` | `native`，`values` = 30 个 ISO-639-1（越界 `degrade`） | `native`，`values` = `["*"]` |
| `languages` | `unsupported` → `degrade`，`max_items=4` | 同左 |
| `prompt` | `unsupported` → `degrade` | `native` |
| `response_format` | `native`，`values` 不含 `diarized_json`（越界 `reject`） | `native`，含全部（越界 `reject`） |
| `temperature` | `unsupported` → `degrade`，`values={0..1}`（越界 400） | 同左 |
| `timestamp_granularities` | `native`，`values=["segment","word"]`，`max_items=2`（越界 `reject`） | `native`，`values=["segment"]`，`max_items=1`（越界 `reject`） |
| `stream` | `unsupported` → `reject` | 同左 |
| `include` | `unsupported` → `degrade`，`values=["logprobs"]`，`max_items=1`（越界 `degrade`） | 同左 |
| `keywords` | `unsupported` → `degrade`，`max_items=50` | `emulated`，`max_items=50` |
| `known_speaker_names` | `unsupported` → `reject`，`1..4` | 同左 |
| `known_speaker_references` | `unsupported` → `reject`，`1..4` | 同左 |
| `chunking_strategy` | `emulated`，`values=["auto","none"]`（越界 `reject`） | 同左 |

`limits`：

| 字段 | qwen3-asr-1.7b | moss-transcribe-diarize |
|---|---|---|
| `formats` | wav/mp3/m4a/flac/ogg/webm | 同左 |
| `max_audio_seconds` | 3600 | 3600 |
| `max_timestamped_audio_seconds` | 300 | —（无 word 能力） |

---

## 5. 响应

三种 JSON 响应的字段与 OpenAI 保持一致；本地模型不具备的字段置 `null`（或按 `null`/`[]` 语义省略）。网关扩展数据 MUST 收进 `x_gateway`，不得新增非 OpenAI 的顶层字段。

### 5.1 `Transcription`（`json`）

```json
{
  "text": "够了，这已经是你第四次了……",
  "languages": [{ "code": "zh" }],
  "logprobs": null,
  "usage": { "type": "duration", "seconds": 193.813 },
  "x_gateway": {
    "model": "qwen3-asr-1.7b",
    "spec_version": "2026-11-26",
    "degraded": [],
    "provider": {}
  }
}
```

- `languages`：模型检测到的语言集合；单值检测也表示为单元素数组。`null` 表示模型无检测能力或未回报；`[]` 表示有能力但未能可靠检测。
- `logprobs`：仅当 `include[]=logprobs` 且模型支持时非 `null`。
- `usage`：见 §5.6。

### 5.2 `TranscriptionVerbose`（`verbose_json`）

```json
{
  "duration": 193.813,
  "language": null,
  "text": "够了，这已经是你第四次了……",
  "segments": [
    {
      "id": 0,
      "seek": null,
      "start": 14.11,
      "end": 17.94,
      "text": "够了，这已经是你第四次了，别忘了你的身份",
      "tokens": null,
      "temperature": null,
      "avg_logprob": null,
      "compression_ratio": null,
      "no_speech_prob": null
    }
  ],
  "words": null,
  "usage": { "type": "duration", "seconds": 193.813 },
  "x_gateway": {
    "model": "moss-transcribe-diarize",
    "spec_version": "2026-11-26",
    "degraded": [],
    "provider": { "segments_source": "segments", "segmentation": "native" }
  }
}
```

- `language`：允许为 `null`（本地模型不回报检测结果时），这是对 OpenAI required 字段的必要偏离。
- `segments` 元素与 OpenAI `TranscriptionSegment` 对齐；模型不提供的数值字段置 `null`。
- **说话人不在 `verbose_json` 的 segment 中**；需要说话人时使用 `diarized_json`。
- `words`：仅当显式请求 `word` 粒度且模型支持时出现；否则为 `null`。

### 5.3 `TranscriptionDiarized`（`diarized_json`）

```json
{
  "duration": 193.813,
  "segments": [
    {
      "id": "0",
      "start": 14.11,
      "end": 17.94,
      "speaker": "A",
      "text": "够了，这已经是你第四次了，别忘了你的身份",
      "type": "transcript.text.segment"
    }
  ],
  "task": "transcribe",
  "text": "够了，这已经是你第四次了……",
  "usage": { "type": "duration", "seconds": 193.813 },
  "x_gateway": {
    "model": "moss-transcribe-diarize",
    "spec_version": "2026-11-26",
    "degraded": [],
    "provider": { "speaker_labels": { "A": "S01", "B": "S02" } }
  }
}
```

- `segments[].id` MUST 为字符串；`type` MUST 为 `transcript.text.segment`。
- `speaker`：提供 `known_speaker_names[]` 时使用登记名称；否则使用 `A`/`B`/… 顺序标签。模型原生标签（如 `S01`）映射到字母后，可在 `x_gateway.provider` 中保留原始映射。
- `segments` MUST 存在；无语音时为 `[]`。
- 模型不支持说话人时，请求该格式按 §6 拒绝。

### 5.4 `text` / `srt` / `vtt`

| 格式 | Content-Type | 内容 |
|---|---|---|
| `text` | `text/plain; charset=utf-8` | 纯文本 |
| `srt` | `text/plain; charset=utf-8` | SubRip；有说话人时 cue 文本前缀 `[S01] `（本规范的字幕扩展，使用模型原生说话人标签） |
| `vtt` | `text/plain; charset=utf-8` | WebVTT；同上 |

- `segments` 为空而 `text` 非空时，字幕渲染为单条 cue（`0 → duration`），保证输出永远可解析。
- 纯文本格式无法携带 `degraded`；需要可观测性时 MUST 使用 JSON 格式。

### 5.5 `null` 与 `[]` 的语义

| 值 | 含义 |
|---|---|
| `languages: null` | 模型无语言检测能力 / 未回报 |
| `languages: []` | 有能力，但未能可靠检测 |
| `language: null` | 未检测到 / 模型不回报 |
| `segments: null`（verbose） | 模型无句级时间戳能力 |
| `segments: []`（verbose） | 有能力，但音频内无语音 |
| `segments: []`（diarized） | 有说话人能力，但音频内无语音 |
| `words: null` | 未请求词级，或模型无此能力 |
| `words: []` | 请求了且模型有此能力，但没有对齐结果 |
| `logprobs: null` | 未请求，或模型不支持 |

### 5.6 `usage`

- 统一为 OpenAI 形状：`{ "type": "duration", "seconds": <float> }`。
- `seconds` 与 `duration` 一致，保留 3 位小数。
- 无法探测时长时为 `null`。
- 本地模型不产生 token 计费结构；`{ "type": "tokens", ... }` 不在本规范范围内。

### 5.7 `degraded` 与 `x_gateway`

`x_gateway` 是唯一的扩展容器：

```json
"x_gateway": {
  "model": "moss-transcribe-diarize",
  "spec_version": "2026-11-26",
  "degraded": [
    {
      "param": "languages",
      "mode": "unsupported",
      "reason": "model does not support candidate language sets; languages were ignored"
    }
  ],
  "provider": {
    "segments_source": "segments",
    "segmentation": "native",
    "diarization": "native"
  }
}
```

- `degraded` 的 `mode` 与能力三态一致（`native` / `emulated` / `unsupported`）。
- 出现 `degraded` 时，响应其余部分仍然**可用**（文本、已有时间戳等保留）。
- 下游若把时间戳用于训练/对齐，MUST 检查 `x_gateway.degraded` 与 `x_gateway.provider.segmentation`。

#### `provider` 的作用

`provider` 是**模型/网关侧的过程与来源信息**，用于解释核心字段是“怎么来的”，回答 `degraded` 无法表达的问题；它不是 OpenAI 契约的一部分，也不参与核心数据的语义。

| 字段 | 作用 |
|---|---|
| `segments_source` | 句级时间戳的来源：模型原生 `segments`、从原始文本解析、或兜底生成 |
| `segmentation` | 句级切分方式：`native`（模型原生）/ `punctuation`（基于已有对齐按标点重切） |
| `diarization` | 说话人来源：`native` / `emulated` |
| `speaker_labels` | `diarized_json` 字母标签与模型原生标签的映射（如 `{"A": "S01"}`） |
| `language_hint` | 入站语言提示（当模型不回报检测结果时，说明依据的是提示而非检测） |
| 其他厂商私有键 | 对齐器名称、模型标识、解析兜底原因等模型私有诊断信息 |

规则：

- `provider` 只承载**来源/过程/诊断**信息；MUST NOT 复制核心字段（`text`、`segments`、`words`），MUST NOT 与核心字段矛盾。
- `degraded` 是**规范性**的：它说明哪些请求能力未满足，下游用于判断结果是否可用；`provider` 是**信息性**的：用于追溯、调试、审计。
- `provider` 的键属于厂商私有扩展，可能随模型/版本变化；客户端 MUST NOT 把它当作稳定业务契约，除非本规范明确要求（如 `provider.segmentation`）。
- 允许为空对象；缺失键表示该信息不适用或未提供。MUST NOT 放入大块原始数据、参考音频或任何密钥。

### 5.8 `response_format` 总表

| 格式 | 响应类型 | Content-Type |
|---|---|---|
| `json` | `Transcription` | `application/json` |
| `verbose_json` | `TranscriptionVerbose` | `application/json` |
| `diarized_json` | `TranscriptionDiarized` | `application/json` |
| `text` | 纯文本 | `text/plain; charset=utf-8` |
| `srt` | SubRip | `text/plain; charset=utf-8` |
| `vtt` | WebVTT | `text/plain; charset=utf-8` |

---

## 6. 参数校验与 `strict`

### 6.1 校验顺序

1. **`limits` 硬边界**：违反即拒绝（`413` / `400` / `415`），与 `strict` 无关。
2. **结构越界**：`values` 为数值范围时的越界、`min_items` / `max_items` 越界、跨参数不一致（`known_speaker_*` 等长）、数组格式非法 → 400 `invalid_request_error`，与 `strict` 无关。
3. **能力/枚举**：以下情况按该参数的 `on_unsupported` 处理：
   - `support: "unsupported"`；
   - `values` 为枚举数组，而请求值不在其中。
   
   结果为 `reject` → 422 `unsupported_parameter`；`degrade` → 继续处理并记入 `x_gateway.degraded`。
4. **`strict=true`**：把本应 `degrade` 的项升级为 422 `unsupported_parameter`；`reject` 与硬限制不受影响。

补充：

- 默认值不触发降级：如 `temperature` 声明 `unsupported`，但请求未传或传 `0` 时不记 `degraded`。
- 空数组视为未提供，不触发 `min_items`。
- 显式请求 `timestamp_granularities=word` 而模型 `values` 只含 `segment` → 值不在枚举中 → 按 `on_unsupported` 处理；输出通道类参数 MUST 为 `reject`，返回 **422**。
- `response_format=diarized_json` 不在模型的 `values` 中 → 同理返回 422。
- `chunking_strategy=vad/fixed` 不在 `values` 中 → 返回 422。

### 6.2 `strict` 契约

| 模式 | 行为 |
|---|---|
| `strict=false`（默认） | `on_unsupported=degrade` 的参数降级并逐条报告 `degraded`；`reject`、结构越界与硬限制仍直接拒绝 |
| `strict=true` | 任何本应 `degrade` 的参数 → `422 unsupported_parameter`，`details.parameters` 附带相关声明 |

`strict=true` 适用于：评测集、训练数据生成、字幕对齐等**错一点就报废**的场景。

`strict` 不改变结构越界与硬限制：数值越界、数量越界、超过 `limits`、`on_unsupported=reject` 的行为完全一致。

### 6.3 参数分类

| 分类 | 参数 | `on_unsupported` 允许值 |
|---|---|---|
| 输出通道/策略 | `timestamp_granularities`、`response_format`、`chunking_strategy`、`stream`、`known_speaker_names`、`known_speaker_references` | 仅 `reject` |
| 提示/附加 | `language`、`languages`、`prompt`、`keywords`、`temperature`、`include` | `reject` 或 `degrade` |

说明：

- 输出通道/策略类参数若忽略会让调用方误以为拿到了某类数据或某种切分方式，因此 MUST NOT 声明 `degrade`；值不在 `values` 或整体不支持时一律 422。
- 提示/附加类参数允许 `degrade`；值不在 `values` 时同样按其 `on_unsupported` 处理。
- 数值范围越界、`min_items` / `max_items` 越界、数组格式非法 → 400，不受 `strict` 影响。
- `known_speaker_names[]` 与 `known_speaker_references[]` 的长度一致性由 §4.1 强制，违反 → 400。

---

## 7. 错误

统一 OpenAI 形状：

```json
{
  "error": {
    "message": "model does not accept a prompt",
    "type": "invalid_request_error",
    "param": "prompt",
    "code": "unsupported_parameter"
  }
}
```

| code | HTTP | 场景 |
|---|---|---|
| `invalid_request_error` | 400 / 415 | 空文件、数量/数值范围越界、数组格式非法、`known_speaker_*` 长度不一致、不支持的音频格式、multipart 解析失败 |
| `model_not_found` | 404 | `model` 不在服务列表 |
| `audio_too_long` | 413 | 超过 `max_audio_seconds` 或 `max_timestamped_audio_seconds` |
| `unsupported_parameter` | 422 | 请求值不在 `values` 枚举中且 `on_unsupported=reject`；`support=unsupported` 且 `on_unsupported=reject`；`strict=true` 将 `degrade` 升级；流式请求 |
| `inference_failed` | 500 | 模型异常；**不透传堆栈** |
| `model_overloaded` | 503 | 队列满（预留） |

---

## 8. 长音频

- 长音频是否切分、以及 `chunking_strategy` 是否被支持，均由模型/实现决定；本规范不强制网关或模型端进行切分或增加支持。
- 每个模型仍 MUST 在 `parameters.chunking_strategy` 中声明 `support` / `values` / `on_unsupported`（可为 `unsupported`）；不支持时的处理遵循 §6。
- 若网关或模型端选择切分：切分后 MUST 把分片时间戳还原为全局时间轴，误差不得超过 1 帧。
- 词级时间戳的音频时长上限由 `limits.max_timestamped_audio_seconds` 声明；显式请求 `word` 且超限时 **413 拒绝**。

---

## 9. 版本化

- `GET /v1/audio/spec` 返回 `{"spec_version":"2026-11-26","models":[...]}`。
- 参数只增不删；废弃走 `Deprecation` 响应头 + 变更记录。
- 能力表变化视为**向后兼容**（客户端 MUST 每次启动读取，禁止硬编码）。
- 响应新增字段视为兼容；删除/改语义必须升版本。

### 变更记录

| 版本 | 变更 | 兼容性 |
|---|---|---|
| `2026-11-26` | `/v1/audio/spec.models[]` 改为 `description`（可选）+ `parameters`（必填，逐 OpenAI 参数声明 `support`/`values`/`min_items`/`max_items`/`on_unsupported`）+ `limits`（资源硬边界）+ `extensions`（自定义 `x_*` 参数）；删除 `capabilities`/`params`；新增 `languages[]`、`known_speaker_names[]`、`known_speaker_references[]`、`include[]`、`response_format=diarized_json`；响应拆为 `Transcription` / `TranscriptionVerbose` / `TranscriptionDiarized`；`usage` 改为 `{type:"duration",seconds}` | **不兼容**：模型能力声明、`usage`、响应形状均变化 |
| `2026-11-25` | `capabilities.languages` → `supported_languages`；请求/能力字段 `hotwords` → `keywords` | **不兼容**：字段改名 |
| `2026-11-01` | 初版 | — |

---

## 10. 新增模型 checklist

1. 实现“原生输出 → 内部结果”的转换层，协议层不直接依赖模型原始输出。
2. 在 `/v1/audio/spec.models[]` 声明 `description`（可选）、`parameters`、`limits`；`parameters` MUST 覆盖全部 OpenAI 参数。
3. 逐参数填写 `support`、`values`、`min_items` / `max_items`、`on_unsupported`；自定义参数放 `extensions`。
4. 核对 §6：数值/数量越界一律 400；枚举值越界与 `support=unsupported` 按其 `on_unsupported` 处理；输出通道类参数 MUST NOT 声明 `degrade`。
5. 用该模型的真实输出验证转换、归一化与渲染路径，并覆盖 HTTP 契约（`/v1/audio/spec`、`parameters` 覆盖、400/422 区分、`strict`、`degraded`、三类响应形状、错误码）。
6. 确认 `segments` 单调、时间戳落在音频范围内。
7. 确认降级项写入 `x_gateway.degraded`；数值/数量越界返回 400；枚举值不在 `values` 或 `support=unsupported` 且 `on_unsupported=reject` 返回 422。
8. 若模型只有超长句，允许在**已有对齐信息**上按标点重新切分，并在 `x_gateway.provider.segmentation` 标注 `punctuation`；**禁止**按字数均分时间。

---

## 11. 单模型部署形态

本规范同样适用于“一个本地模型自带一个 server”的部署：不需要多模型注册表，也不需要模型协商缓存。单模型 server 与多模型网关对客户端是**同一契约**，区别只在内部实现。

### 11.1 必须保留

- 端点、multipart 字段、`response_format`、错误形状与 §2–§7 完全一致。
- `GET /v1/audio/spec` 返回 `models[]`，恰好一条，内含该模型的 `description`、`parameters`、`limits`。
- `GET /v1/audio/spec` 照常返回 `spec_version`。
- `parameters` / `limits` 仍是静态声明，但 MUST 诚实；`degraded` 与 `strict` 仍 MUST 生效，**不得**因为“只有一个模型”就静默丢弃参数。
- 内部结果与协议渲染分离：原生输出 → 内部结果 → 三类 OpenAI 响应/文本视图，让协议正确性独立于推理实现。

### 11.2 `model` 字段

- 单模型 server 的 `model` MUST 精确匹配其固定 id，不做别名。
- 不匹配时返回 `404 model_not_found`，`details.available` 只含该 id。这样同一份 OpenAI SDK 代码在单模型 server 与多模型网关之间切换时无需改动。

### 11.3 可以简化

| 多模型网关 | 单模型 server |
|---|---|
| 多模型注册与切换 | 固定一个模型实现 |
| 能力协商缓存 | 常量 `parameters` + `limits` |
| 跨模型差异处理 | 只处理本模型已知的取值/能力校验点 |
| `model_not_found` 的可用列表 | 固定 id 校验 |

### 11.4 配置与加载

- 模型路径、设备、精度可由环境变量注入；启动即加载或首次请求懒加载均可。
- 单模型 server 不需要为“其他模型”预留 `chunking_strategy` 占位逻辑：模型原生支持长音频时按 §8 处理；是否切分由网关/模型端决定，若切分则按 §8 的时间轴还原要求执行。

### 11.5 测试

- 契约测试与多模型网关相同：覆盖 `/v1/audio/spec` 单条、`parameters` 覆盖、400/422 区分、`strict`、`degraded`、三类响应形状与错误码。
- 用该模型的真实输出验证归一化与渲染路径。

---

## 12. 与 OpenAI 的差异汇总

### 12.1 有意的本地偏离

- 本地模型不回报检测结果时，`TranscriptionVerbose.language` 允许为 `null`（OpenAI 为 required）。
- 时间/数值字段模型无法提供时置 `null`，不伪造。
- `usage` 只支持 `{"type": "duration", "seconds": ...}`；不产生 token 计费结构。
- `srt` / `vtt` 的说话人 `[S01] ` 前缀是本规范的字幕扩展；OpenAI 原生字幕不含说话人。
- 所有网关扩展收进 `x_gateway`（OpenAI 响应无此字段，但 openai-python 允许额外字段）。

### 12.2 范围外

- `/v1/audio/translations` 与 `task="translate"`：不在本规范范围内。

### 12.3 实现状态说明

- `gpt-transcribe` 本身不支持 diarization；OpenAI 侧说话人分离仍依赖已标记弃用的 `gpt-4o-transcribe-diarize`。本规范不据此假设所有模型都具备说话人能力，而是按 `parameters.response_format.values` 是否包含 `diarized_json`、以及 `x_gateway.provider.diarization` 逐模型声明与实际处理。

---

## 相关文档

- [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) — 通用 manifest/目录/发布规则
- [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md) — host 持有的 OpenAI/Anthropic 服务契约
- [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) — `entry.kind`、script/engine/native 后端
