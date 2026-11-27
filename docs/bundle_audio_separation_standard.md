# Audio separation bundle category standard (`POST /v1/audio/separations`)

<p align="right"><strong>English</strong> · <a href="bundle_audio_separation_standard.zh-CN.md">简体中文</a></p>

> **Category supplement.** The generic manifest, layout, entry, runtime, weights and publishing rules remain authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) (zh: [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)). This page adds only audio-separation-specific serving requirements and does not repeat those rules.
>
> **Host-owned serving behavior.** In engine mode the host owns the standard routes, authentication, inference-slot concurrency, request logging, SSE transport and protocol-error translation, all defined in [bundle_serve_protocols.md](bundle_serve_protocols.md) (zh: [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)). This page does not redefine them.
>
> **Gateway model selection.** A direct `flashcli serve` deployment serves exactly one model, so requests carry no `model` field. The multi-model flashserver `/v1` gateway routes custom paths with a query selector: `POST /v1/audio/separations?model=<namespace/name:version>`. The gateway resolves the resident model, **strips the query before forwarding**, and leaves the path and body unchanged. The body contract never gains a `model` field, and responses never contain one.

This standard defines the calling contract for audio-separation bundles: models that split an input recording into **dialogue speech** (`voice`) and **everything else** (`ambience`). It covers the wire format, stem semantics, response/error shapes, execution requirements, and security limits for `POST /v1/audio/separations`.

```bash
# Direct deployment (one model per endpoint)
flashcli serve <org>/<name>:<version> --host 0.0.0.0 --port 8080
#   POST http://<host>:8080/v1/audio/separations

# Multi-model gateway (selector required for custom paths)
#   POST http://<gateway>/v1/audio/separations?model=<org>/<name>:<version>
```

---

## 1. Scope and positioning

| Item | Value |
|---|---|
| API version | `v1` |
| Endpoint | `POST /v1/audio/separations` |
| Style | OpenAI-compatible REST API with local-execution extensions |
| Execution | Synchronous only |
| Input | `wav`, `mp3` — upload, URL, or server-local path |
| Output | `wav`, `mp3`, written to a server-local directory |
| Result | JSON with server-local stem file paths |

- One bundle represents **one separation model**; callers do not choose a model inside the payload. Instrument-level separation (drums, bass, guitar, piano) is outside this version's scope.
- The API is OpenAI-*shaped* (resource naming, JSON parameters, error object), but OpenAI has no native audio-separation endpoint; this path and its fields are local extensions, and the design does not imply official OpenAI support.
- The model MUST provide the semantics defined in §3. Renaming the outputs of a generic vocal/accompaniment separator is **not** conformance; if the capability is missing, the service reports it (§7).
- Execution is synchronous. v1 defines no streaming response and no asynchronous job or status-polling API. The response `id` identifies the request only; it is not a job id.
- Audio separation bundles are packaged in **engine mode** and expose this route as a custom route. The host mounts custom routes from `register_routes(app)` ahead of its own routes and keeps the standard routes host-owned. Because the route is not a host capability, it is outside the host inference gate: the bundle MUST validate requests, serialize GPU work, and enforce its own limits, while still following the host's auth and logging behavior described in [bundle_serve_protocols.md](bundle_serve_protocols.md).

---

## 2. Endpoint

| Item | Definition |
|---|---|
| HTTP method | `POST` |
| Endpoint | `/v1/audio/separations` |
| `Content-Type` | `multipart/form-data` or `application/json` |
| `Accept` | `application/json` |
| Execution | Synchronous |
| Response | JSON (`application/json`) |

The endpoint is the same for both request encodings; the input source determines the encoding (§4.2, §5).

---

## 3. Stem types

Exactly two stem types are defined. Do not subdivide instruments.

| Stem | Name | Definition |
|---|---|---|
| `voice` | Dialogue speech | Human speaking only: conversation, narration, interviews, and similar speech. MUST NOT contain singing, lead vocals, or backing harmonies. |
| `ambience` | Everything else | All sound other than dialogue speech: background music, singing, harmonies, drums, bass, guitar, piano, room tone, machinery, animals, and any other non-dialogue audio. |

### 3.1 Selection and defaults

- When `stems` is omitted, both `voice` and `ambience` are produced, in that order.
- When `stems` is present, only the requested types are produced, returned in request order.
- Requesting only `voice` yields dialogue speech only; requesting only `ambience` yields all remaining sound.
- The model MUST support every requested stem type. An unknown stem value returns `400 unsupported_stem`; a defined type the model cannot produce returns `400 unsupported_separation_capability`.
- `ambience` is the general residual class. It does not mean "ambient/atmosphere sounds only".

### 3.2 Output semantics

- `voice` and `ambience` MUST be two separations of the **same input**.
- The stems MUST preserve the original timeline as closely as possible: start position, duration, sample rate, channel count, and inter-stem synchronization.
- `voice` MUST NOT contain singing, lead vocals, or harmonies. `ambience` MUST contain all remaining sound and MUST NOT classify individual instruments.
- Requested stems are returned only when they were actually generated; a partially successful response MUST NOT claim `status: "completed"`.

### 3.3 Model capability

- The model MUST distinguish dialogue speech from all other sound.
- A model that only separates "vocals (speech and singing) vs. accompaniment" does not satisfy `voice` until it can exclude singing and music vocals. Until then the service MUST report `unsupported_separation_capability` instead of emitting mislabeled stems.
- Capability MUST be validated at request time. Silent degradation to a semantically different output is forbidden.

---

## 4. Request

`POST /v1/audio/separations` with `multipart/form-data` or `application/json`. JSON requests use a single JSON object as the body.

### 4.1 Common parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `stems` | array[string] | No | `["voice","ambience"]` | Stem types to produce |
| `prompt` | string | No | `""` | Text hint for models that support prompt-guided separation |
| `output_format` | string | No | `wav` | Output encoding: `wav` or `mp3` |
| `output_directory` | string | Yes | — | Server-local output directory |

`prompt` rules:

- The default is the empty string, meaning "no hint".
- Models with prompt-guided separation SHOULD honor the hint (for example, which sound to keep or remove).
- Models without prompt support MUST ignore `prompt` and MUST NOT return a parameter error because it was provided.
- `prompt` never overrides the stem semantics in §3; the requested `stems` remain authoritative.

In multipart requests all non-file fields are strings: `stems` is a JSON array string (for example `["voice","ambience"]`), and `output_format` / `output_directory` are plain strings.

### 4.2 Input source: exactly one

| Parameter | Type | Encoding | Description |
|---|---|---|---|
| `file` | file | `multipart/form-data` | Uploaded audio file |
| `audio_url` | string | `application/json` | Audio URL downloaded by the server |
| `audio_path` | string | `application/json` | Server-local audio file path |

- A request MUST provide **exactly one** of `file`, `audio_url`, `audio_path`. Zero sources or more than one returns `400 invalid_input` naming the offending parameter.
- The service MUST NOT accept a request that mixes an uploaded file with a URL or path source.
- `audio_path` is resolved on the machine running the model process, not on the client. The service MUST confine it to directories it is authorized to read; a missing or unreadable file returns `404 file_not_found`.
- `audio_url` is fetched by the service. Scheme, destination and redirects are restricted per §9.

### 4.3 Model selection

The request body has no `model` field. Model selection depends on the frontend:

| Frontend | Selection |
|---|---|
| Direct `flashcli serve` | The deployment is the model. The separation request has no `model` parameter and no negotiation. |
| flashserver `/v1` gateway | Custom paths require the query selector `?model=<namespace/name:version>`, for example `/v1/audio/separations?model=aodianyun/audio-separator:1.0.0`. The gateway resolves the resident model of that reference, removes the query, and forwards the same path, headers and body. |

Rules:

- The query selector is a **gateway** concern. A bundle MUST ignore the query string and MUST NOT require, parse, or echo `model`.
- Do not add a `model` JSON field or multipart field. The body contract is identical on both frontends.
- Responses never include a `model` field; the endpoint (direct) or the resolved gateway target identifies the model.
- The selector applies equally to JSON and multipart requests; it is part of the URL, not the payload.
- A missing or unknown selector is rejected by the gateway before forwarding; it is not an audio-separation error and does not reach the bundle.

### 4.4 Audio format requirements

| Format | Input | Output |
|---|---|---|
| WAV | Supported | Supported |
| MP3 | Supported | Supported |

- Video input is not supported; callers must extract audio first.
- The file extension MUST match the actual audio encoding.
- The service is responsible for decoding, resampling, and encoding as needed.
- `output_format` defaults to `wav`; `mp3` output requires an MP3 encoder. FFmpeg is not mandatory; any suitable codec library may be used.

---

## 5. Request examples

### 5.1 Multipart upload

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -F "file=@input.wav" \
  -F 'stems=["voice","ambience"]' \
  -F "prompt=" \
  -F "output_format=wav" \
  -F "output_directory=/data/output/"
```

MP3 input with defaults for `stems` and `prompt`:

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -F "file=@input.mp3" \
  -F "output_format=mp3" \
  -F "output_directory=/data/output/"
```

### 5.2 URL input

```bash
curl -X POST "http://localhost:8000/v1/audio/separations" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://example.com/input.wav",
    "stems": ["voice", "ambience"],
    "prompt": "Keep all dialogue speech",
    "output_format": "wav",
    "output_directory": "/data/output/"
  }'
```

The service downloads the audio and performs separation. `prompt` may be omitted and is then treated as the empty string.

### 5.3 Server-local path input

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

`audio_path` and `output_directory` are both server-local. When client and service share a filesystem, the same path may be used on both sides; an existing local file never needs to be re-uploaded over HTTP.

### 5.4 Through the gateway

```bash
curl -X POST "http://gateway:8790/v1/audio/separations?model=aodianyun/audio-separator:1.0.0" \
  -H "Content-Type: application/json" \
  -d '{"audio_path": "/data/input/input.wav", "output_directory": "/data/output/"}'
```

The gateway strips `?model=...`; the bundle receives the same body as in §5.3.

---

## 6. Response

Successful requests return `200 OK` and `application/json`.

### 6.1 Completed WAV

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

### 6.2 MP3 output

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

### 6.3 Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier for this request |
| `object` | string | Always `audio.separation` |
| `status` | string | `completed` after a successful synchronous run |
| `input` | object | Input audio information |
| `input.filename` | string | Input file name |
| `input.format` | string | Input audio format |
| `input.duration` | number | Audio duration in seconds |
| `output` | object | Output information |
| `output.format` | string | Output audio format |
| `output.directory` | string | Output directory |
| `output.stems` | array | Produced stems |
| `output.stems[].type` | string | `voice` or `ambience` |
| `output.stems[].format` | string | Stem file format |
| `output.stems[].path` | string | Server-local path of the stem file |

### 6.4 Response semantics

- `id` identifies this request only; it is not an asynchronous job id.
- `output.stems` contains only stems that were requested **and** successfully generated.
- All returned paths are server-local. A client on another machine needs a shared mount to read them; v1 defines no download endpoint.
- `voice` and `ambience` are two separations of the same input and MUST stay mutually time-aligned.
- The response never contains `model`; the deployment or resolved gateway target identifies the model.
- `status` MUST NOT be `completed` when the request failed or only partially succeeded (§7).

---

## 7. Errors

Errors use JSON and the OpenAI-style error object:

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

| HTTP | `code` | `param` | Scenario |
|---|---|---|---|
| 400 | `invalid_input` | offending source field | Zero input sources, or more than one of `file` / `audio_url` / `audio_path` |
| 400 | `unsupported_audio_format` | `file` / `audio_url` / `audio_path` | Input is not WAV/MP3, or cannot be decoded as the declared format |
| 400 | `unsupported_stem` | `stems` | A requested stem is not one of `voice` / `ambience` |
| 400 | `unsupported_separation_capability` | — | The model cannot produce the requested stem semantics (for example, it cannot exclude singing) |
| 404 | `file_not_found` | `audio_path` | Server-local input file does not exist or is unreadable |
| 500 | `separation_failed` | — | Inference or output encoding failed |

Rules:

- `message` is human-readable; `type` is `invalid_request_error` for 4xx and `server_error` for 5xx.
- `param` names the offending field and is omitted when no single field applies.
- A failed request MUST NOT return `status: "completed"` or stem paths for stems that were not produced.
- Because this route is bundle-owned, the bundle is responsible for emitting this shape; the host's protocol-error translation covers host-mounted routes.

---

## 8. Server execution requirements

Execution order:

1. Receive the request; validate the input source, audio format, and stem types.
2. Check the model's capability for the requested separation; if a non-empty `prompt` is present and the model supports hints, apply it.
3. Read the uploaded file, the server-local file, or the downloaded URL content.
4. Decode and preprocess the audio as needed.
5. Run separation.
6. Obtain the PCM waveforms for `voice` and `ambience`.
7. Encode the waveforms to the requested format (`wav` or `mp3`).
8. Write the stem files into `output_directory`.
9. Return the JSON result with the generated paths.

Additional requirements:

- `output_directory` may be created automatically when missing.
- A synchronous request MUST wait until every requested stem is written before returning success.
- Output files from different requests MUST NOT overwrite each other; a unique per-request subdirectory is recommended.
- Audio separation is GPU-bound: the bundle SHOULD run one inference at a time per device. The custom route is outside the host inference gate, so serialization is the bundle's responsibility.
- `voice` MUST NOT contain singing or harmonies; `ambience` MUST contain all remaining sound without instrument-level classification.
- If the model cannot meet the speech-versus-singing requirement, report `unsupported_separation_capability`; never silently downgrade and return a semantically wrong stem.
- If the model does not support `prompt`, ignore it rather than returning a parameter error.

---

## 9. Security and limits

- **Local paths.** `audio_path` may only access directories the service is authorized to read. `output_directory` must be a writable server-local directory; implementations SHOULD confine both to configured roots (for example an input root and an output root).
- **URLs.** Downloads MUST restrict the scheme to `http`/`https`, restrict destination ports, block loopback/private/link-local addresses by default, bound the redirect chain, and re-validate every hop. This prevents access to internal services (SSRF).
- **Size and duration.** Implementations MUST cap upload size, decoded audio duration, and processing time, and MUST return a client error in the §7 shape when a cap is exceeded (v1 does not fix a dedicated `code` for this case).
- **Output collisions.** Per-request subdirectories (or equivalent unique naming) MUST be used so concurrent requests cannot clobber each other's stems.
- **Path traversal.** Stem paths and `output_directory` handling MUST NOT allow escaping the authorized roots.
- The service SHOULD avoid logging audio content; request logging is host-owned (see [bundle_serve_protocols.md](bundle_serve_protocols.md)) and must not add payload dumps.

---

## 10. Supported scope (v1)

| Capability | v1 |
|---|---|
| WAV input | Supported |
| MP3 input | Supported |
| WAV output | Supported |
| MP3 output | Supported |
| File upload | Supported |
| URL input | Supported |
| Server-local path input | Supported |
| Server-local path output | Supported |
| Dialogue speech stem `voice` | Supported, subject to model capability |
| Residual stem `ambience` | Supported, subject to model capability |
| Default two-stem output | Supported |
| `prompt` hint | Supported where the model has the capability; ignored otherwise |
| `model` request field | Not provided (the deployed bundle or gateway selector determines the model) |
| Synchronous execution | Supported |
| Streaming execution | Not supported |
| Asynchronous jobs / status polling | Not supported |
| Video input / audio-track extraction | Not supported |
| Instrument stems (drums, bass, guitar, piano) | Outside this version's scope |

---

## 11. Conformance checklist

- [ ] `POST /v1/audio/separations` accepts both `multipart/form-data` and `application/json`.
- [ ] Exactly one of `file` / `audio_url` / `audio_path` is enforced; violations return `400 invalid_input` with the offending `param`.
- [ ] `stems` defaults to `["voice","ambience"]`, honors subsets, and returns stems in request order.
- [ ] Singing, lead vocals, and harmonies never appear in `voice`; `ambience` carries all remaining sound.
- [ ] Models without the required discrimination return `400 unsupported_separation_capability` instead of mislabeled output.
- [ ] `prompt` is ignored without error when unsupported and never changes stem semantics.
- [ ] `output_format` supports `wav` and `mp3`, defaults to `wav`, and matches `output.format` / stem `format`.
- [ ] `output_directory` is respected, may be created, and concurrent requests cannot overwrite each other.
- [ ] The success response matches §6 exactly, contains only produced stems, and uses server-local paths.
- [ ] Errors match §7: HTTP status, `code`, `param`, and `type`.
- [ ] Execution is synchronous: no streaming, no async job id, and success waits for all requested stems.
- [ ] Local paths are confined, URL fetches are SSRF-guarded, and size/duration/timeout caps are enforced.
- [ ] On the flashserver gateway the service works with `?model=` stripped; no `model` field exists in the body or the response.
- [ ] The published tree passes `flashcli bundle validate` and the checklist above through `flashcli serve`.

---

## Related documents

- [bundle_publish_standard.md](bundle_publish_standard.md) — manifest, layout, weights, runtime, publishing
- [bundle_serve_protocols.md](bundle_serve_protocols.md) — host-owned engine-mode serving surface
- [bundle_execution_abi.md](bundle_execution_abi.md) — `entry.kind` and script/engine/native backends
