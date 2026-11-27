# MiniMax-Remover video erase serving specification (flashcli serve)

<p align="right"><strong>English</strong> · <a href="bundle_video_erase_standard.zh-CN.md">简体中文</a></p>

> **Category supplement.** The generic manifest, layout, weights, runtime and publishing rules remain authoritative
> in [bundle_publish_standard.md](bundle_publish_standard.md) (zh:
> [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)). This page adds only the video-erase API
> requirements.
>
> **Gateway passthrough.** Video-erase bundles use `format_version: 4`, engine mode, a `ServeEngine`, and
> `register_routes(app)` for the native `/v1/video/erase` family. The flashserver `/v1` gateway forwards these custom
> paths, including job and file URLs, to the model's serve endpoint.
>
> **Generic rules are not repeated.** Manifest/layout/entry/runtime/weights/publishing are defined in
> [bundle_publish_standard.md](bundle_publish_standard.md); engine-mode host behavior (standard routes, auth,
> concurrency, request logging, SSE transport, error translation) is defined in
> [bundle_serve_protocols.md](bundle_serve_protocols.md). This page adds only video-erase routes, schemas, limits, and
> acceptance.

This document is the **server-side specification for the MiniMax-Remover FlashRT bundle**, and defines both:

1. the **native HTTP API** for video erase (mask-guided video inpainting / object, subtitle, and watermark removal);
2. the **`erase` extension specification** on **OpenAI Chat Completions / Responses**.

Applicable implementation: `aodianyun/MiniMax-Remover:1.0.4` (FlashRT `4ad99bd3`), `flashcli serve` engine mode. API
version: `video.erase` v1.

---

## 1. Positioning

MiniMax-Remover is a **mask-guided** video inpainting model: the input is a video (or frame sequence) plus a
per-frame/static binary mask, and the output is a video of the same length as the input whose masked regions are
completed. The model does not accept text instructions; the removed region is determined entirely by the mask. The
`prompt` field is accepted only for protocol compatibility and does not take part in computation.

How the serving mode differs from OCR / LLM bundles:

| Dimension | OCR / LLM | This service |
|---|---|---|
| Input | single image / text | video, frame sequence, frame archive + mask video/image/sequence |
| Compute | single forward pass / token generation | 12-step flow matching + VAE, tens of seconds on one GPU |
| Output | JSON text | frame directory, ZIP, MP4, or base64 frames |
| Streaming | token / line deltas | phase progress (queued → media → inference → encode) |
| Calibration | none | online shape-based calibration on the first real request + graph capture |

---

## 2. Architecture and host boundaries

Engine mode: the host builds FastAPI and owns the standard routes, authentication, the inference-slot concurrency gate, request logging, SSE transport, and protocol-error translation. It calls `ServeEngine.register_routes(app)`; the video-erase routes below are mounted there. The host contract is defined in [bundle_serve_protocols.md](bundle_serve_protocols.md); this page adds only the video-erase routes, media contract, jobs, and limits.

## 3. Startup and lifecycle

The host owns model load/warmup, readiness and the serve lifecycle; see [bundle_serve_protocols.md](bundle_serve_protocols.md). The bundle only implements `ServeEngine.load` / `warmup` and the erase handlers.

## 4. Authentication and general conventions

The host owns authentication, the concurrency gate, request logging and the JSON error envelope; see [bundle_serve_protocols.md](bundle_serve_protocols.md). Video-erase media limits, output rules and security checks are category-specific and are defined in §5 and §13–§15.

## 5. Media input specification

All media fields (`video`, `frames`, `mask`, `masks`, `frames_archive`) accept the same set of source forms:

| Form | Example |
|---|---|
| data URL | `data:video/mp4;base64,...`, `data:image/png;base64,...`, `data:application/zip;base64,...` |
| Bare base64 | base64 of PNG/JPEG/MP4/ZIP bytes |
| HTTP(S) | `https://example.com/clip.mp4` (private-network/loopback rejected by default, see §15) |
| Local path | a file path under `/data/clips/tennis/`, a relative path, `~/...` |
| `file://` | `file:///data/clips/mask.png` |

An object form may also be used to specify the source explicitly:

```json
{"url": "https://..."}
{"path": "/data/..."}
{"base64": "..."}
{"data_url": "data:video/mp4;base64,..."}
```

### 5.1 Video sources

- `video`: one video container (MP4/MOV/WebM/MKV/AVI/MPEG/TS). Decoded into RGB frames with the ffmpeg in the image;
  `fps` is read from the container.
- `frames`: a list of frames (in array order), or a single ZIP/video/image. List elements may be images, ZIPs, or short
  videos; images inside a ZIP are sorted by numeric filename (`00000.png`, `1.jpg`, etc.), non-numeric names are sorted
  lexicographically.
- `frames_archive` / `archive`: explicit ZIP frame archive. The ZIP may contain a `frames/` subdirectory.
- `video` and `frames`/`frames_archive` are mutually exclusive.

### 5.2 Mask sources

| Field | Form | Semantics |
|---|---|---|
| `mask` | image / video / ZIP | image = static mask (broadcast to all frames); video/ZIP = per-frame mask |
| `mask_video` | video / ZIP / image | explicit form for a per-frame mask |
| `masks` | list of images/videos/ZIPs | a list of length 1 is treated as static; a list at least as long as the frame count is truncated; frames not covered are all-black (no erase) |

- Masks are 8-bit grayscale; `> mask_threshold` (default 127) is the removal region.
- When the mask size differs from the frames, it is resized to the frame size with nearest-neighbor.
- When the mask has fewer frames than the input, the remaining frames are treated as having no removal region; frames
  beyond the input frame count are ignored.
- When all masks are empty, no inference is performed and the source frames are output directly
  (`mask.has_region=false`).

### 5.3 Frame rate and dimensions

- Video input: `input.fps` comes from the container; frame-sequence input defaults to 24 fps (can be overridden with
  `output.fps`).
- All frames are unified to the first frame's dimensions (bilinear resize when inconsistent).
- `options.width` / `options.height` (both MUST be given together) resize before inference; internally the frames are
  padded to a multiple of 16, and the output is cropped back to the working size.
- Tail frames: the Wan VAE decodes 4k+1 frames; decoded frames beyond the input frame count are discarded, and missing
  tail frames use the source frames directly, guaranteeing output frame count = input frame count.

---

## 6. Native API: `POST /v1/video/erase`

### 6.1 JSON request

```json
{
  "model": "minimax_remover",
  "video": "data:video/mp4;base64,...",
  "mask": "data:image/png;base64,...",
  "options": {
    "num_inference_steps": 12,
    "iterations": 6,
    "seed": 42,
    "max_frames": 0,
    "width": 0,
    "height": 0,
    "mask_threshold": 127
  },
  "output": {"format": "frames", "fps": 0, "crf": 18},
  "async": false
}
```

Frame-sequence form:

```json
{
  "frames": ["data:image/png;base64,...", "..."],
  "masks": ["data:image/png;base64,...", "..."],
  "output": {"format": "zip"}
}
```

### 6.2 multipart/form-data

The same endpoint accepts file uploads for `curl` use:

```bash
curl -s http://127.0.0.1:8080/v1/video/erase \
  -H "Authorization: Bearer sk-xxx" \
  -F video=@clip.mp4 -F mask=@mask.png \
  -F 'output={"format":"frames"}'
```

Fields: `video`, `mask`, `mask_video`, `frames` (repeatable), `masks` (repeatable), `frames_archive`, `options` (JSON
string), `output` (JSON string), `async`, `model`, `prompt`. Uploaded files are saved under `output_root/_uploads/` and
deleted when the job ends.

### 6.3 Synchronous response (200)

```json
{
  "object": "video.erase.result",
  "version": 1,
  "job_id": "erase-0123456789abcdef",
  "status": "completed",
  "model": "minimax_remover",
  "engine": "flashrt-minimax-remover",
  "route": "fp8-nvfp4-graph",
  "precision": "fp8+nvfp4",
  "device": "NVIDIA GeForce RTX 5060 Ti",
  "input": {"kind": "video", "width": 432, "height": 240,
            "frames": 70, "fps": 24.0, "bytes": 1234567},
  "mask": {"mode": "image", "static": true, "frames": 70,
           "has_region": true, "region_fraction": 1.0, "threshold": 127},
  "options": {"num_inference_steps": 12, "iterations": 6, "seed": 42,
              "max_frames": 0, "width": 0, "height": 0,
              "mask_threshold": 127},
  "output": {"format": "frames", "fps": 24.0, "frame_count": 70,
             "width": 432, "height": 240,
             "frames": [{"index": 0, "filename": "000000.png",
                          "url": "/v1/video/erase/files/<job>/frames/000000.png"}],
             "zip_url": null, "mp4_url": null},
  "timing": {"queue_ms": 0.2, "media_ms": 380.1, "inference_ms": 3120.4,
             "encode_ms": 240.8, "e2e_ms": 3741.5},
  "memory": {"peak_allocated_gib": 2.78, "peak_reserved_gib": 3.10},
  "prompt": null
}
```

### 6.4 Asynchronous response (202)

A request with `"async": true` returns immediately:

```json
{
  "object": "video.erase.job",
  "id": "erase-0123456789abcdef",
  "job_id": "erase-0123456789abcdef",
  "status": "queued",
  "created_at": 1795079000,
  "queue_s": null,
  "cancel_requested": false
}
```

Afterwards poll `GET /v1/video/erase/jobs/{job_id}`; on completion the same object carries the full result.

---

## 7. Job API

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/video/erase` | `async=false` executes synchronously; `async=true` returns 202 + job |
| `GET` | `/v1/video/erase/jobs` | Recent job list (`?limit=N`, default 50) |
| `GET` | `/v1/video/erase/jobs/{job_id}` | Job status; contains the full result when completed |
| `GET` | `/v1/video/erase/jobs/{job_id}/result` | Result alias; returns the original error status on failure |
| `DELETE` | `/v1/video/erase/jobs/{job_id}` | Completed job: delete the record and output; running job: request cancellation |
| `GET` | `/v1/video/erase/files/{job_id}/{path}` | Download frames / ZIP / MP4 / result.json |
| `GET` | `/v1/video/erase/info` | Capabilities, limits, defaults, runtime state |

Job states: `queued` → `running` → `completed` | `failed` | `cancelled`.

- Cancellation: a queued job is cancelled immediately; **a running CUDA Graph cannot be interrupted mid-way**, so the
  job runs to completion and keeps its result, and the response is marked `cancel_requested=true`.
- A synchronous request that exceeds `request_timeout_sec` (default 900 s) returns 504; the job keeps running in the
  background and can be polled or deleted with the job id.
- Output of completed jobs is retained for `output_retention_sec` (default 3600 s), and at most `max_jobs` (default 64)
  records are kept; when exceeded, the oldest completed jobs and their directories are deleted.

---

## 8. Output formats

`output.format`:

| Value | Artifact | Response field |
|---|---|---|
| `frames` (default) | `<job>/frames/%06d.png` | `output.frames[].url` |
| `zip` | `<job>/output.zip` (`frames/%06d.png` + `result.json`) | `output.zip_url` |
| `mp4` | `<job>/output.mp4` (H.264, `libx264`, `-movflags +faststart`) | `output.mp4_url` |
| `base64` | nothing written to disk; PNG frames inlined as base64 | `output.frames[].content_base64` |
| `none` | metadata only | — |

- `output.fps`: MP4 frame rate; 0 = input video fps, frame sequences default to 24.
- `output.crf`: x264 CRF (0–51, default 18); `output.quality` 1–10 may be used as an alternative.
- Odd MP4 width/height is padded to even with edge replication (required by yuv420p).
- The total PNG byte size of `base64` output is limited by `max_inline_bytes` (default 32 MiB); exceeding it returns 413,
  so `zip`/`frames` are recommended instead.
- All download paths are confined to the job directory (path traversal returns 400).

---

## 9. OpenAI extension: Chat Completions

`POST /v1/chat/completions` extends the standard OpenAI vision message format:

- **video part**: `{"type": "video_url", "video_url": {"url": "<media source>"}}` (aliases: `video`, `input_video`).
- **mask part**: `{"type": "mask_image" | "mask_url" | "video_mask", ...}`.
- **`image_url` part**: when the same request already has a video source, it is used as a mask: 1 image = static mask;
  multiple images = per-frame masks in order. This lets standard OpenAI vision clients pass a mask without private parts.
- Text parts are accepted as `prompt` but do not take part in computation.
- `tools` / `functions` / `n>1` return 400 (this model does not generate tokens).

### 9.1 `erase` extension object (request)

```json
{
  "erase": {
    "mask": "<media source>",      // alternative to a mask part in content
    "mask_video": "<media source>",
    "masks": ["<media source>", "..."],
    "frames": "<ZIP or frame-list source>",  // a video_url in content may also be used
    "options": {"num_inference_steps": 12, "iterations": 6, "seed": 42,
                 "max_frames": 0, "width": 0, "height": 0,
                 "mask_threshold": 127},
    "output": {"format": "frames", "fps": 0, "crf": 18},
    "content_format": "text",      // text | json
    "async": false
  }
}
```

`extra_body.erase` (the OpenAI Python SDK style) is also accepted.

### 9.2 Response

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "minimax_remover",
  "choices": [{"index": 0,
    "message": {"role": "assistant",
                "content": "Erased the masked region from 70 frame(s) ..."},
    "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "erase": {"object": "video.erase.result", "...": "same as §6.3"}
}
```

- `content` is summary text by default; with `erase.content_format=json` or
  `response_format={"type":"json_object"}` it is the JSON string of the `erase` object.
- The structured result is always in top-level `erase`; clients should read that object instead of parsing the text.
- With `async=true` a normal `chat.completion` is returned and `erase` is the job snapshot
  (`object: video.erase.job`).

### 9.3 Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="sk-xxx")
resp = client.chat.completions.create(
    model="minimax_remover",
    messages=[{"role": "user", "content": [
        {"type": "video_url", "video_url": {"url": video_data_url}},
        {"type": "image_url", "image_url": {"url": mask_data_url}},
    ]}],
    extra_body={"erase": {"output": {"format": "zip"}}},
)
print(resp.model_extra["erase"]["output"]["zip_url"])
```

---

## 10. OpenAI extension: Responses

`POST /v1/responses`:

- `input` is a string or a list of items;
- the `input_text` inside `input_text` / `message.content` is used as the prompt;
- `input_video` / `video_url` items (or message content parts) are the video source;
- `input_image` / `image_url` / `input_mask` items are the mask (same semantics as §9);
- the `erase` extension object is the same as §9.1;
- `previous_response_id`, `tools` return 400 (stateless, no tools).

The response is a standard `response` object with an additional top-level `erase`; `output_text` is the same as
`content` in §9.2.

---

## 11. Streaming (SSE)

When `stream: true`:

- Chat Completions: a sequence of `chat.completion.chunk`; each progress chunk carries
  `erase: {object: "video.erase.progress", phase, ...}`, the final chunk carries `finish_reason: "stop"`, `usage` (if
  `stream_options.include_usage`) and the full `erase` result, followed by `data: [DONE]`.
- Responses: `response.created` / `response.in_progress` / `response.erase.progress` / `response.output_text.*` /
  `response.completed` events.

Phases:

| phase | Meaning |
|---|---|
| `queued` | enqueued |
| `running` | the worker started executing |
| `media` | decoding video/frames, loading the mask |
| `inference` | calibration / graph capture / CUDA Graph replay |
| `inference_done` | inference finished (with timing and memory) |
| `encode` | packaging the output |
| `completed` / `failed` / `cancelled` | terminal state |

Client disconnect: queued jobs are cancelled; running jobs continue to completion (the GPU is not interruptible) and
their results are retained and remain pollable.

---

## 12. Error codes

| HTTP | code | Description |
|---|---|---|
| 400 | `video_required` | missing video/frame source |
| 400 | `mask_required` | missing mask |
| 400 | `unsupported_parameter` | tools / n>1 / unknown option |
| 400 | `invalid_video` / `invalid_image` / `invalid_archive` | decode failure |
| 400 | `invalid_media_url` / `private_media_url` | illegal URL / SSRF blocked |
| 400 | `local_media_paths_disabled` / `local_media_outside_root` | local path policy |
| 401 | `invalid_api_key` | authentication failure |
| 404 | `job_not_found` / `file_not_found` | job/file not found |
| 413 | `media_too_large` / `frames_limit_exceeded` / `pixels_limit_exceeded` / `inline_limit_exceeded` | limit exceeded |
| 503 | `server_busy` / `not_ready` | queue full / not loaded |
| 504 | `request_timeout` | synchronous wait timed out (job continues) |
| 500 | `internal_error` | inference failure (including CUDA OOM) |

---

## 13. Limits and defaults

`GET /v1/video/erase/info` returns the effective runtime values. Serve options:

| Option | Default | Description |
|---|---|---|
| `--model-name` | `minimax_remover` | model id reported in responses |
| `--api-key` | empty | `/v1/*` authentication |
| `--device` | `cuda:0` | CUDA device |
| `--attention` | `auto` | built-in SageAttention-2; explicit `FLASHRT_ATTN_MODE` |
| `--step-cache` | `auto` | 4-step cache at 0/3/7/11; `none` or a list of step numbers |
| `--max-queue` | 32 | cap on requests/jobs waiting for the GPU; beyond it 503 |
| `--request-timeout-sec` | 900 | synchronous request wait cap; 504 on timeout |
| `--max-frames` | 121 | frame cap per clip; 413 above it |
| `--max-pixels` | 0 | working-resolution pixel cap; 0 = automatic (399360 on ≥15 GiB cards, 103680 on 12 GiB cards) |
| `--max-video-bytes` | 256 MiB | video/mask video source size |
| `--max-image-bytes` | 20 MiB | single image/frame |
| `--max-archive-bytes` | 512 MiB | total size after ZIP extraction |
| `--max-inline-bytes` | 32 MiB | total base64 output |
| `--max-graphs` | 4 | number of resident CUDA Graph shapes |
| `--max-jobs` | 64 | number of completed jobs retained |
| `--output-root` | `<tmp>/minimax_remover_serve` | job output root directory |
| `--output-retention-sec` | 3600 | output retention seconds (0 = limited only by max_jobs) |
| `--public-base-url` | empty | absolute prefix for output URLs |
| `--default-steps` | 12 | default denoise steps |
| `--default-iterations` | 6 | default mask dilation iterations |
| `--default-seed` | 42 | default latent seed |
| `--default-output-format` | `frames` | default output format |
| `--mask-threshold` | 127 | default mask threshold |
| `--allow-private-media-urls` | false | allow private-network URLs (SSRF protection) |
| `--media-url-timeout-sec` | 15 | URL download timeout |
| `--media-url-ports` | `80,443` | allowed URL ports (empty = any) |
| `--allow-local-media-paths` | true | allow local paths / `file://` |
| `--local-media-root` | empty | sandbox root for local paths |

Request-level `options` may override `num_inference_steps`, `iterations`, `seed`, `max_frames` (truncation),
`width`/`height`, and `mask_threshold`; `step_cache` and `attention` can only be set at startup.

---

## 14. Precision, performance, and memory

Test protocol (same data for every round): DAVIS `tennis` 70 frames / `bmx-trees` 80 frames, 432x240, 12 steps,
`iterations=6`, seed 42; E2E is the median of 5 replays after calibration/capture; peak memory comes from the PyTorch
allocator. The baseline is an fp16 diffusers implementation on the same machine with the same data.

| GPU | Route | Baseline E2E | FlashRT E2E | Speedup | Peak memory | cosine mean/min | PSNR |
|---|---|---:|---:|---:|---|---:|---:|
| RTX 5060 Ti 16 GB | `fp8-nvfp4-graph` | 16.86 s | **3.12 s** | **5.40×** | 2.78 GiB | 0.9988 / 0.9977 | 31.84 dB |
| RTX 4060 Ti 16 GB | `fp8-graph` | 20.94 s | **4.03 s** | **5.20×** | 4.03 GiB | 0.9995 / 0.9984 | 33.91 dB |
| RTX 3060 12 GB | `int8-graph` | 27.27 s | **6.27 s** | **4.35×** | 3.89 GiB | 0.9996 / 0.9994 | 38.07 dB |

832x480 production shape (RTX 5060 Ti): baseline 99.26 s → **21.88 s** (4.54×), peak alloc 7.24 GiB / NVML 11.03 GiB;
RTX 4060 Ti: 118.54 s → 24.64 s (4.81×), peak alloc 8.99 GiB / NVML 12.48 GiB.

### 14.1 `flashcli serve` measurements (same tennis 70-frame data)

| GPU | Route | First-request E2E (calibration+capture; `none` output) | Steady-state inference | Steady-state E2E (none) | Steady-state E2E (frames output) | Steady-state peak memory | NVML peak | vs. run output |
|---|---|---:|---:|---:|---:|---:|---:|---|
| RTX 5060 Ti 16 GB | `fp8-nvfp4-graph` | 13.78 s | 3.108 s | 3.33 s | 3.78 s | 2.74 GiB | 4285 MiB | pixel-identical |
| RTX 4060 Ti 16 GB | `fp8-graph` | 19.07 s | 4.04–4.07 s | 4.24–4.26 s | 4.72 s | 3.41 GiB | 4832 MiB | pixel-identical |
| RTX 3060 12 GB | `int8-graph` | 47.28 s | 6.34 s | 6.54 s | 7.03 s | 2.08 GiB | 3619 MiB | pixel-identical |

- The first request includes online quantization calibration + CUDA Graph capture; `none` output excludes PNG
  packaging.
- Steady-state `inference_ms` matches the median of `flashcli run` (difference < 1%); serve's extra E2E is HTTP/JSON,
  ZIP decoding, and output packaging (~0.2 s + encoding).
- Comparison with the run path uses the same lossless frame ZIP / mask ZIP and seed; decoded pixels match exactly frame
  by frame (cos=1.0, PSNR=99); PNG file md5 differs because of different compression levels.

The full per-round optimization record is in the `docs/round_table.md` of optimization campaign `rsi-task-170`
(`/data/inference-campaigns/rsi-task-170`) and in the report on FlashHub. Serving-mode overhead is HTTP
encoding/decoding, video decode/encode, and PNG/ZIP packaging; the `timing` fields separate this from `inference_ms`
so the overhead can be pinpointed.

---

## 15. Security

- By default only public `http`/`https` addresses are allowed; URLs that resolve to loopback/private/link-local
  addresses return 400 immediately (can be relaxed explicitly with `--allow-private-media-urls true`).
- URL ports are restricted to 80/443 by default; at most 4 redirects, with every hop re-validated.
- Local paths are allowed by default (resident-service scenario); for production deployments it is recommended to set
  `--local-media-root /data/media` to restrict readable directories, or `--allow-local-media-paths false` to disable
  them entirely.
- Upload/download size, frame count, pixel count, and total ZIP extraction size all have hard caps.
- Output download paths are checked for escape from the job directory.

---

## 16. Compatibility notes

- This service is a **video erase model**, not an LLM: it provides no token generation, tool calling, reasoning
  channel, or Anthropic Messages API. `/v1/completions` returns 400 and points to the supported endpoints.
- The `usage` field keeps the OpenAI shape but is 0; real timings are in `erase.timing`.
- One bundle covers SM86 / SM89 / SM120; A100/H100/Hopper are not supported.
- Serve is provided from version `1.0.4`; `flashcli run`'s CLI is unchanged from 1.0.3.

---

## Related

- [bundle_publish_standard.md](bundle_publish_standard.md) — manifest, layout, weights, publishing
- [bundle_serve_protocols.md](bundle_serve_protocols.md) — engine-mode `ServeEngine`, capabilities, `register_routes`
- [bundle_execution_abi.md](bundle_execution_abi.md) — `entry.kind` execution backends
