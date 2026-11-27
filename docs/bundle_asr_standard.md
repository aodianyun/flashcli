# ASR bundle serving standard (OpenAI-compatible API)

<p align="right"><strong>English</strong> · <a href="bundle_asr_standard.zh-CN.md">简体中文</a></p>

Defines a calling contract for locally deployed open-source ASR models that is **shaped like OpenAI `/v1/audio/transcriptions`** while honestly expressing model differences.

This specification applies to any local ASR model. `qwen3-asr-1.7b` and `moss-transcribe-diarize` appear only as declaration examples and do not limit its scope.

---


> **Category supplement.** The generic manifest, layout, weights, runtime and publishing rules remain authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) (zh: [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)). Engine-mode host behavior (standard routes, auth, concurrency, request logging, SSE transport, error translation) is defined in [bundle_serve_protocols.md](bundle_serve_protocols.md); this page adds only ASR-specific routes, schemas, limits, and acceptance.
>
> **FlashCLI integration.** A new ASR bundle uses `format_version: 4`. It may use either form:
>
> - **engine mode**: implement `ServeEngine.transcribe` for `/v1/audio/transcriptions` / `translations`, and use `register_routes(app)` for `/v1/audio/spec`;
> - **script mode**: the bundle owns the HTTP server and implements the complete contract below.
>
> Declare `openai.audio.transcriptions` (and `openai.audio.translations` when supported) in `entry.serve.capabilities`.
>
> **Gateway passthrough.** The flashserver `/v1` gateway proxies `/v1/audio/transcriptions` / `translations` and forwards custom paths such as `/v1/audio/spec` to the model's serve endpoint. Extra multipart fields are forwarded, but the model must tolerate them. The richer model declaration lives at `/v1/audio/spec.models`.

## 0. Specification Positioning

This specification is a **contract**, not an implementation guide.

- Implementers can use it to build an API gateway compatible with multiple ASR models, or to add OpenAI-compatible `/v1/audio/transcriptions` support to a single ASR model.
- Implementations may freely choose their internal structure, model loading method, inference backend, and deployment shape, as long as they follow this specification.
- This document defines only the wire format, capability declarations, and behavioral contract. Model loading, inference backends, deployment shape, and other implementation details are outside the normative text (see §11 for single-model deployment guidance).

---

## 1. Design Principles

**P1 Three-layer separation.** The protocol has three layers that do not overlap:

| Layer | Content | Cost of change |
|---|---|---|
| L1 Wire format | Paths, multipart fields, response shapes | High (client dependency) |
| L2 Parameters and limits | `parameters` (per-parameter support and handling) and `limits` (resource hard limits) | Medium (grows with models) |
| L3 Extension namespace | Vendor-private data under `x_gateway` | Low (free to add or remove) |

**P2 Observable degradation.** For any parameter it cannot honor, an implementation MUST choose one of two options: reject with an explanation, or degrade and report each item in `degraded`. **Silent ignoring is forbidden.**

**P3 Do not fabricate data.** If there are no word-level timestamps, do not output `words`; if there is no speaker, do not output `speaker`. Prefer `null` over guessing.

**P4 One internal result, three OpenAI response types.** `response_format` changes only the presentation; `json` / `verbose_json` / `diarized_json` render as OpenAI's `Transcription` / `TranscriptionVerbose` / `TranscriptionDiarized` respectively, without changing the information model.

**P5 Declaration and policy in one place.** Each model self-describes in `/v1/audio/spec.models[]`: `description` (optional, human-readable), `parameters` (required, per-OpenAI-parameter support and handling when unsupported), and `limits` (resource hard limits independent of parameter shape). A client can read one declaration to determine behavior.

---

## 2. Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/v1/audio/transcriptions` | Transcription, `multipart/form-data` |
| GET | `/v1/audio/spec` | Specification version and model declaration registry (`models[]`) |

`GET /v1/audio/spec` returns the specification version and the model declaration registry:

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

## 3. Request

`POST /v1/audio/transcriptions`, `Content-Type: multipart/form-data`.

Array parameters appear in multipart as **repeated fields with brackets** (`languages[]`, `keywords[]`, `timestamp_granularities[]`, `known_speaker_names[]`, `known_speaker_references[]`, `include[]`); this matches openai-python's encoding.

| Field | Required | Default | Contract |
|---|---|---|---|
| `file` | MUST | — | Audio file. The gateway does not require clients to transcode in advance; decoding is the model side's responsibility; the format MUST be within the model's `limits.formats` |
| `model` | MUST | — | MUST match the deployed model id; when proxied by flashserver the gateway sends the full bundle ref, which the engine may normalize. Aliases are not supported |
| `language` | MAY | `auto` | A single language hint, ISO-639-1 (`zh`/`en`/`yue`) |
| `languages[]` | MAY | `[]` | The set of languages that **may** occur in this audio, ISO-639-1; may coexist with `language`; if the model does not support sets, degrade per §6 |
| `prompt` | MAY | `""` | **Terminology/context hint**, not an instruction (see §3.2) |
| `response_format` | MAY | `json` | `json` / `text` / `srt` / `verbose_json` / `vtt` / `diarized_json` |
| `temperature` | MAY | `0` | Degrade when non-zero and the model decodes deterministically (see §6) |
| `timestamp_granularities[]` | MAY | `[]` | `word` / `segment`; reject when a granularity the model lacks is explicitly requested (see §6) |
| `stream` | MAY | `false` | This specification does not define streaming responses; 422 when the model does not support it |
| `include[]` | MAY | `[]` | Additional return information; currently only `logprobs`; degrade when unsupported |
| `keywords[]` | MAY | `[]` | Hotword/terminology guidance; when the model has no dedicated channel, the gateway converts it (e.g., injecting it into the transcription instruction as a "hotword hint") |
| `known_speaker_names[]` | MAY | `[]` | Registered speaker names; the count is constrained by `parameters.known_speaker_names.max_items` (see §3.4) |
| `known_speaker_references[]` | MAY | `[]` | Reference audio corresponding to the names in order, as data URLs, 2–10 seconds each (see §3.4) |
| `chunking_strategy` | MAY | `auto` | `auto` / `vad` / `fixed` / `none`; support and handling are declared by the model (see §8) |
| `strict` | MAY | `false` | Specification extension, see §6 |

### 3.1 Time

- The unit is always **seconds**, as `float`, rounded to 3 decimal places (millisecond precision).
- `segments` MUST be monotonically non-decreasing and MUST fall within `[0, duration]`.

### 3.2 Redefining the Semantics of `prompt`

With the same field, Whisper-family models treat it as "continuation of prior text", while generative models treat it as an "instruction". Passing it through directly produces unstable output (the model may start summarizing or explaining).

Rules:

- `prompt` MUST carry only glossaries, proper nouns, and context snippets.
- The gateway is responsible for translation: Whisper family → decoder prefix; generative models → concatenate into the transcription instruction; models without prompt support → ignore and record in `degraded`.
- No model may output explanatory text, headings, or Markdown because of `prompt`.

### 3.3 Language

- Use only ISO-639-1 externally; `null` means "not detected/not reported", not `"unknown"`.
- On output, if the model returns a full name (e.g., `Chinese`), the gateway normalizes it to ISO-639-1.
- `language` is a single-value hint; `languages[]` is a candidate set. They have different semantics and may coexist.
- The allowed values of `language` are declared by `parameters.language.values`; when a value is not listed, handle it according to that parameter's `on_unsupported` (e.g., `degrade` means ignore the hint and record it).
- If `languages[]` is declared `support: "unsupported"`, handle it according to `on_unsupported` (e.g., `degrade` means ignore the set and record it in `degraded`).

### 3.4 Speakers and Named Speakers

- Requests for speaker diarization MUST use `response_format=diarized_json`. If the model does not support speakers, reject per §6.
- `known_speaker_names[]` and `known_speaker_references[]` are **paired by index**: each name has one reference audio (data URL, 2–10 seconds, same format as `file`). Their lengths MUST match, and the item counts MUST be within the respective `min_items` / `max_items` ranges (1–4 for OpenAI); otherwise return 400.
- When named speakers are provided, `diarized_json.segments[].speaker` MUST use the registered names; otherwise use sequential labels `A`/`B`/….
- If the model does not support named speakers, requests carrying `known_speaker_*` MUST be **rejected** per §6 and MUST NOT be degraded to anonymous diarization.

### 3.5 Custom Parameters (Beyond OpenAI)

- Custom parameters MUST use the `x_` prefix, e.g., `x_vad_threshold`; arrays keep the bracket convention: `x_<name>[]`.
- Custom parameters MUST be declared in `/v1/audio/spec` under `extensions`; an undeclared `x_*` field returns 400.
- Keys in `extensions` are logical names (without the `x_` prefix), and each item additionally declares `type` (`string` / `number` / `boolean` / `array`).
- Custom parameters MUST NOT share a name with OpenAI parameters, and MUST NOT use `x_gateway` (reserved for responses).
- When using openai-python, pass them via `extra_body={"x_vad_threshold": 0.5}`; the SDK encodes them as flat fields.

---

## 4. Capability and Parameter Declarations

Each item in `GET /v1/audio/spec` `models[]` has four parts: `description` (optional), `parameters` (required), `limits` (required), and `extensions` (optional, custom parameters).

The following is a declaration example for a single model:

```json
{
  "id": "moss-transcribe-diarize",
  "object": "model",
  "description": "MOSS transcription + anonymous speaker diarization; segment-level timestamps only.",
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
      "note": "Hotword hint injected into the transcription instruction"
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
      "note": "Each item is a 2–10 second audio data URL, matched to known_speaker_names[] by index"
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

### 4.1 Declaration Parts and Field Semantics

**`description` (optional)**: A human-readable description, for understanding the model only; it does not participate in validation.

**`parameters` (required)**: MUST cover the complete OpenAI parameter list:

`file`, `model`, `language`, `languages`, `prompt`, `response_format`, `temperature`, `timestamp_granularities`, `stream`, `include`, `keywords`, `known_speaker_names`, `known_speaker_references`, `chunking_strategy`.

Each entry has the following fields:

| Field | Values | Rules |
|---|---|---|
| `support` | `native` / `emulated` / `unsupported` | Required |
| `values` | Array / `"*"` / `{"min":..,"max":..}` | Optional; allowed values for a scalar, or allowed values for array elements; `"*"` means unrestricted |
| `min_items` / `max_items` | Integer | Array parameters only; declares the element count range |
| `on_unsupported` | `reject` / `degrade` | Required when `support=unsupported` or when `values` is an enum array |
| `note` | String | Optional human-readable description |

- When `values` is an **enum array**: a request value not in it → handle per `on_unsupported` (`reject` → 422, `degrade` → degrade and record `degraded`).
- When `values` is a **numeric range** (`{"min":..,"max":..}`): out of range, `min_items` / `max_items` out of range, cross-parameter inconsistency, or invalid array format → 400 `invalid_request_error`.
- `values: "*"` means unrestricted.
- An empty array is treated as "not provided" and does not trigger `min_items`.
- If `parameters` is missing any OpenAI parameter → the capability declaration is invalid.
- `known_speaker_names[]` and `known_speaker_references[]` MUST have the same length, otherwise 400; this cross-parameter rule is mandated by this specification and is not expressed in the declaration.

**`limits` (required)**: Contains only model resource hard limits unrelated to the shape/count of OpenAI parameters:

| Field | Meaning |
|---|---|
| `formats` | Acceptable input containers |
| `max_audio_seconds` | Maximum audio duration |
| `max_timestamped_audio_seconds` | Maximum audio duration allowed when requesting timestamps (word-level) |
| `max_upload_bytes` | Maximum upload size |

- Violating `limits` always results in rejection (`413` / `400` / `415`), regardless of `strict`.
- List only the entries applicable to the model.

**`extensions` (optional)**: Declarations of custom parameters beyond OpenAI; keys are logical names (wire names are `x_<name>`), and each item additionally contains `type`; the other fields are the same as above:

```json
"extensions": {
  "vad_threshold": {
    "type": "number",
    "support": "native",
    "values": { "min": 0, "max": 1 }
  }
}
```

### 4.2 Declaration Summary of the Two Example Models

The following summary illustrates how the same specification maps to different models. It is not a normative requirement; actual capabilities are determined by each model's `/v1/audio/spec` declaration.

| Parameter | qwen3-asr-1.7b | moss-transcribe-diarize |
|---|---|---|
| `file` / `model` | `native` | `native` |
| `language` | `native`, `values` = 30 ISO-639-1 codes (out of range `degrade`) | `native`, `values` = `["*"]` |
| `languages` | `unsupported` → `degrade`, `max_items=4` | Same |
| `prompt` | `unsupported` → `degrade` | `native` |
| `response_format` | `native`, `values` does not contain `diarized_json` (out of range `reject`) | `native`, contains all (out of range `reject`) |
| `temperature` | `unsupported` → `degrade`, `values={0..1}` (out of range 400) | Same |
| `timestamp_granularities` | `native`, `values=["segment","word"]`, `max_items=2` (out of range `reject`) | `native`, `values=["segment"]`, `max_items=1` (out of range `reject`) |
| `stream` | `unsupported` → `reject` | Same |
| `include` | `unsupported` → `degrade`, `values=["logprobs"]`, `max_items=1` (out of range `degrade`) | Same |
| `keywords` | `unsupported` → `degrade`, `max_items=50` | `emulated`, `max_items=50` |
| `known_speaker_names` | `unsupported` → `reject`, `1..4` | Same |
| `known_speaker_references` | `unsupported` → `reject`, `1..4` | Same |
| `chunking_strategy` | `emulated`, `values=["auto","none"]` (out of range `reject`) | Same |

`limits`:

| Field | qwen3-asr-1.7b | moss-transcribe-diarize |
|---|---|---|
| `formats` | wav/mp3/m4a/flac/ogg/webm | Same |
| `max_audio_seconds` | 3600 | 3600 |
| `max_timestamped_audio_seconds` | 300 | — (no word capability) |

---

## 5. Response

The fields of the three JSON responses match OpenAI; fields unavailable in local models are set to `null` (or omitted according to the `null`/`[]` semantics). Gateway extension data MUST be placed under `x_gateway`; no new non-OpenAI top-level fields may be added.

### 5.1 `Transcription` (`json`)

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

- `languages`: The set of languages detected by the model; a single detected language is also represented as a one-element array. `null` means the model has no detection capability or did not report; `[]` means it has the capability but could not detect reliably.
- `logprobs`: Non-`null` only when `include[]=logprobs` and the model supports it.
- `usage`: See §5.6.

### 5.2 `TranscriptionVerbose` (`verbose_json`)

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

- `language`: May be `null` (when the local model does not report detection results); this is a necessary deviation from OpenAI's required field.
- `segments` elements align with OpenAI `TranscriptionSegment`; numeric fields the model cannot provide are set to `null`.
- **Speakers are not in `verbose_json` segments**; use `diarized_json` when speakers are needed.
- `words`: Present only when `word` granularity is explicitly requested and the model supports it; otherwise `null`.

### 5.3 `TranscriptionDiarized` (`diarized_json`)

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

- `segments[].id` MUST be a string; `type` MUST be `transcript.text.segment`.
- `speaker`: When `known_speaker_names[]` is provided, use the registered names; otherwise use sequential labels `A`/`B`/…. After mapping native model labels (e.g., `S01`) to letters, the original mapping may be retained in `x_gateway.provider`.
- `segments` MUST be present; `[]` when there is no speech.
- If the model does not support speakers, requests for this format are rejected per §6.

### 5.4 `text` / `srt` / `vtt`

| Format | Content-Type | Content |
|---|---|---|
| `text` | `text/plain; charset=utf-8` | Plain text |
| `srt` | `text/plain; charset=utf-8` | SubRip; when speakers are present, cue text is prefixed with `[S01] ` (a subtitle extension of this specification, using native model speaker labels) |
| `vtt` | `text/plain; charset=utf-8` | WebVTT; same as above |

- When `segments` is empty but `text` is non-empty, subtitles render as a single cue (`0 → duration`) so the output is always parseable.
- Plain-text formats cannot carry `degraded`; use a JSON format when observability is required.

### 5.5 Semantics of `null` and `[]`

| Value | Meaning |
|---|---|
| `languages: null` | Model has no language detection capability / did not report |
| `languages: []` | Capable, but could not detect reliably |
| `language: null` | Not detected / model does not report |
| `segments: null` (verbose) | Model has no segment-level timestamp capability |
| `segments: []` (verbose) | Capable, but no speech in the audio |
| `segments: []` (diarized) | Has speaker capability, but no speech in the audio |
| `words: null` | Word-level not requested, or model lacks the capability |
| `words: []` | Requested and model has the capability, but no alignment result |
| `logprobs: null` | Not requested, or model does not support it |

### 5.6 `usage`

- Uniformly OpenAI-shaped: `{ "type": "duration", "seconds": <float> }`.
- `seconds` matches `duration` and is rounded to 3 decimal places.
- `null` when duration cannot be detected.
- Local models do not produce token billing structures; `{ "type": "tokens", ... }` is out of scope for this specification.

### 5.7 `degraded` and `x_gateway`

`x_gateway` is the only extension container:

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

- `degraded`'s `mode` is consistent with the three capability states (`native` / `emulated` / `unsupported`).
- When `degraded` is present, the rest of the response remains **usable** (text and existing timestamps are preserved).
- If downstream uses timestamps for training/alignment, it MUST check `x_gateway.degraded` and `x_gateway.provider.segmentation`.

#### Role of `provider`

`provider` is **process and provenance information on the model/gateway side**, explaining how core fields came to be and answering questions that `degraded` cannot express. It is not part of the OpenAI contract and does not participate in the semantics of core data.

| Field | Role |
|---|---|
| `segments_source` | Source of segment-level timestamps: native model `segments`, parsed from raw text, or fallback-generated |
| `segmentation` | Segment-level segmentation method: `native` (native to the model) / `punctuation` (re-split by punctuation based on existing alignment) |
| `diarization` | Speaker source: `native` / `emulated` |
| `speaker_labels` | Mapping between `diarized_json` letter labels and native model labels (e.g., `{"A": "S01"}`) |
| `language_hint` | Inbound language hint (when the model does not report detection results, indicates that the basis is the hint rather than detection) |
| Other vendor-private keys | Model-private diagnostic information such as aligner names, model identifiers, and parser fallback reasons |

Rules:

- `provider` carries only **provenance/process/diagnostic** information; it MUST NOT duplicate core fields (`text`, `segments`, `words`) and MUST NOT contradict them.
- `degraded` is **normative**: it states which requested capabilities were not satisfied, and downstream uses it to judge whether results are usable. `provider` is **informational**: for tracing, debugging, and auditing.
- `provider` keys are vendor-private extensions and may change with the model/version; clients MUST NOT treat them as a stable business contract unless this specification explicitly requires it (e.g., `provider.segmentation`).
- An empty object is allowed; a missing key means the information does not apply or was not provided. It MUST NOT contain large raw data, reference audio, or any secrets.

### 5.8 `response_format` Summary

| Format | Response type | Content-Type |
|---|---|---|
| `json` | `Transcription` | `application/json` |
| `verbose_json` | `TranscriptionVerbose` | `application/json` |
| `diarized_json` | `TranscriptionDiarized` | `application/json` |
| `text` | Plain text | `text/plain; charset=utf-8` |
| `srt` | SubRip | `text/plain; charset=utf-8` |
| `vtt` | WebVTT | `text/plain; charset=utf-8` |

---

## 6. Parameter Validation and `strict`

### 6.1 Validation Order

1. **`limits` hard limits**: violation results in immediate rejection (`413` / `400` / `415`), regardless of `strict`.
2. **Structural violations**: `values` numeric range out of range, `min_items` / `max_items` out of range, cross-parameter inconsistency (`known_speaker_*` equal length), invalid array format → 400 `invalid_request_error`, regardless of `strict`.
3. **Capability/enum**: the following cases are handled according to the parameter's `on_unsupported`:
   - `support: "unsupported"`;
   - `values` is an enum array and the request value is not in it.

   The result is `reject` → 422 `unsupported_parameter`; `degrade` → continue processing and record in `x_gateway.degraded`.
4. **`strict=true`**: upgrades items that would otherwise `degrade` to 422 `unsupported_parameter`; `reject` and hard limits are unaffected.

Additional notes:

- Default values do not trigger degradation: e.g., if `temperature` is declared `unsupported` but the request omits it or passes `0`, `degraded` is not recorded.
- An empty array is treated as not provided and does not trigger `min_items`.
- If `timestamp_granularities=word` is explicitly requested but the model's `values` contains only `segment` → value not in the enum → handle per `on_unsupported`; output-channel parameters MUST be `reject`, returning **422**.
- `response_format=diarized_json` is not in the model's `values` → likewise return 422.
- `chunking_strategy=vad/fixed` is not in `values` → return 422.

### 6.2 `strict` Contract

| Mode | Behavior |
|---|---|
| `strict=false` (default) | Parameters with `on_unsupported=degrade` are degraded and reported individually in `degraded`; `reject`, structural violations, and hard limits are still rejected directly |
| `strict=true` | Any parameter that would otherwise `degrade` → `422 unsupported_parameter`, with `details.parameters` containing the relevant declarations |

`strict=true` is suitable for scenarios where **a small error invalidates the result**, such as evaluation sets, training-data generation, and subtitle alignment.

`strict` does not change structural violations or hard limits: numeric out-of-range, count out-of-range, exceeding `limits`, and `on_unsupported=reject` behave exactly the same.

### 6.3 Parameter Categories

| Category | Parameters | Allowed `on_unsupported` |
|---|---|---|
| Output channel/policy | `timestamp_granularities`, `response_format`, `chunking_strategy`, `stream`, `known_speaker_names`, `known_speaker_references` | `reject` only |
| Hint/additional | `language`, `languages`, `prompt`, `keywords`, `temperature`, `include` | `reject` or `degrade` |

Notes:

- If output-channel/policy parameters are ignored, callers may mistakenly believe they received a certain type of data or a certain chunking method, so they MUST NOT declare `degrade`; when a value is not in `values` or the parameter is entirely unsupported, always return 422.
- Hint/additional parameters may `degrade`; when a value is not in `values`, handle it according to their `on_unsupported` as well.
- Numeric range violations, `min_items` / `max_items` violations, and invalid array format → 400, unaffected by `strict`.
- The length consistency of `known_speaker_names[]` and `known_speaker_references[]` is mandated by §4.1; violation → 400.

---

## 7. Errors

Uniform OpenAI shape:

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

| code | HTTP | Scenario |
|---|---|---|
| `invalid_request_error` | 400 / 415 | Empty file, count/numeric range out of range, invalid array format, inconsistent `known_speaker_*` lengths, unsupported audio format, multipart parsing failure |
| `model_not_found` | 404 | `model` is not in the service list |
| `audio_too_long` | 413 | Exceeds `max_audio_seconds` or `max_timestamped_audio_seconds` |
| `unsupported_parameter` | 422 | Request value not in `values` enum and `on_unsupported=reject`; `support=unsupported` and `on_unsupported=reject`; `strict=true` upgrades `degrade`; streaming request |
| `inference_failed` | 500 | Model exception; **stack traces are not passed through** |
| `model_overloaded` | 503 | Queue full (reserved) |

---

## 8. Long Audio

- Whether long audio is split, and whether `chunking_strategy` is supported, are determined by the model/implementation; this specification does not require the gateway or model side to split or to add support.
- Each model MUST still declare `support` / `values` / `on_unsupported` for `parameters.chunking_strategy` (which may be `unsupported`); handling when unsupported follows §6.
- If the gateway or model side chooses to split: after splitting, chunk timestamps MUST be restored to the global timeline with an error of no more than 1 frame.
- The maximum audio duration for word-level timestamps is declared by `limits.max_timestamped_audio_seconds`; explicitly requesting `word` beyond the limit results in **413 rejection**.

---

## 9. Versioning

- `GET /v1/audio/spec` returns `{"spec_version":"2026-11-26","models":[...]}`.
- Parameters are only added, never removed; deprecation uses the `Deprecation` response header plus the changelog.
- Changes to the capability table are considered **backward compatible** (clients MUST read it at every startup and MUST NOT hard-code it).
- New response fields are considered compatible; removal or semantic changes require a version bump.

### Changelog

| Version | Change | Compatibility |
|---|---|---|
| `2026-11-26` | `/v1/audio/spec.models[]` changed to `description` (optional) + `parameters` (required; per-OpenAI-parameter declaration of `support`/`values`/`min_items`/`max_items`/`on_unsupported`) + `limits` (resource hard limits) + `extensions` (custom `x_*` parameters); removed `capabilities`/`params`; added `languages[]`, `known_speaker_names[]`, `known_speaker_references[]`, `include[]`, `response_format=diarized_json`; responses split into `Transcription` / `TranscriptionVerbose` / `TranscriptionDiarized`; `usage` changed to `{type:"duration",seconds}` | **Incompatible**: model capability declarations, `usage`, and response shapes all changed |
| `2026-11-25` | `capabilities.languages` → `supported_languages`; request/capability field `hotwords` → `keywords` | **Incompatible**: field renaming |
| `2026-11-01` | Initial version | — |

---

## 10. Checklist for Adding a Model

1. Implement a conversion layer from "native output → internal result"; the protocol layer must not depend directly on raw model output.
2. Declare `description` (optional), `parameters`, and `limits` in `/v1/audio/spec.models[]`; `parameters` MUST cover all OpenAI parameters.
3. Fill in `support`, `values`, `min_items` / `max_items`, and `on_unsupported` for each parameter; put custom parameters in `extensions`.
4. Check §6: numeric/count out-of-range always 400; enum value out-of-range and `support=unsupported` are handled according to their `on_unsupported`; output-channel parameters MUST NOT declare `degrade`.
5. Use the model's real output to verify the conversion, normalization, and rendering paths, and cover the HTTP contract (`/v1/audio/spec`, `parameters` coverage, 400/422 distinction, `strict`, `degraded`, the three response shapes, and error codes).
6. Confirm `segments` are monotonic and timestamps fall within the audio range.
7. Confirm degraded items are written to `x_gateway.degraded`; numeric/count out-of-range returns 400; enum values not in `values`, or `support=unsupported` with `on_unsupported=reject`, return 422.
8. If the model only produces very long sentences, re-splitting by punctuation on top of **existing alignment information** is allowed, and `x_gateway.provider.segmentation` must be marked `punctuation`; **splitting time evenly by character count is forbidden**.

---

## 11. Single-Model Deployment

This specification also applies to deployments where "one local model comes with its own server": no multi-model registry and no model negotiation cache are required. A single-model server and a multi-model gateway present the **same contract** to clients; the difference is only in internal implementation.

### 11.1 Must Keep

- Endpoints, multipart fields, `response_format`, and error shapes are exactly the same as §2–§7.
- `GET /v1/audio/spec` returns `models[]` with exactly one entry containing that model's `description`, `parameters`, and `limits`, plus `spec_version`.
- `parameters` / `limits` are still static declarations, but MUST be honest; `degraded` and `strict` MUST still take effect; parameters MUST NOT be silently dropped just because "there is only one model".
- Separate internal results from protocol rendering: native output → internal result → three OpenAI response/text views, so protocol correctness is independent of the inference implementation.

### 11.2 `model` Field

- A single-model server's `model` MUST exactly match its fixed id; no aliases.
- On mismatch, return `404 model_not_found`, with `details.available` containing only that id. This lets the same OpenAI SDK code switch between a single-model server and a multi-model gateway without changes.

### 11.3 What Can Be Simplified

| Multi-model gateway | Single-model server |
|---|---|
| Multi-model registration and switching | One fixed model implementation |
| Capability negotiation cache | Constant `parameters` + `limits` |
| Cross-model difference handling | Only handle value/capability validation points known for this model |
| Available list for `model_not_found` | Fixed id validation |

### 11.4 Configuration and Loading

- Model path, device, and precision may be injected via environment variables; eager loading at startup or lazy loading on first request are both acceptable.
- A single-model server does not need to reserve `chunking_strategy` placeholder logic for "other models": when the model natively supports long audio, handle it per §8; whether to split is decided by the gateway/model side, and if splitting occurs, follow the timeline restoration requirements in §8.

### 11.5 Testing

- Contract tests are the same as for a multi-model gateway: cover a single `/v1/audio/spec` model entry, `parameters` coverage, 400/422 distinction, `strict`, `degraded`, the three response shapes, and error codes.
- Use the model's real output to verify the normalization and rendering paths.

---

## 12. Differences from OpenAI

### 12.1 Intentional Local Deviations

- When a local model does not report detection results, `TranscriptionVerbose.language` may be `null` (OpenAI requires it).
- Time/numeric fields that the model cannot provide are set to `null`; they are not fabricated.
- `usage` supports only `{"type": "duration", "seconds": ...}`; it does not produce token billing structures.
- The speaker `[S01] ` prefix in `srt` / `vtt` is a subtitle extension of this specification; native OpenAI subtitles contain no speaker.
- All gateway extensions are placed under `x_gateway` (OpenAI responses do not have this field, but openai-python allows extra fields).

### 12.2 Out of Scope

- `/v1/audio/translations` and `task="translate"`: out of scope for this specification.

### 12.3 Implementation Status Notes

- `gpt-transcribe` itself does not support diarization; speaker diarization on the OpenAI side still relies on the deprecated `gpt-4o-transcribe-diarize`. This specification therefore does not assume all models have speaker capability; instead, it declares and handles it per model based on whether `parameters.response_format.values` contains `diarized_json` and on `x_gateway.provider.diarization`.

---

## Related documents

- [bundle_publish_standard.md](bundle_publish_standard.md) — generic manifest/layout/publishing rules
- [bundle_serve_protocols.md](bundle_serve_protocols.md) — host-owned OpenAI/Anthropic serve contract
- [bundle_execution_abi.md](bundle_execution_abi.md) — `entry.kind`, script/engine/native backends
