# TTS bundle standard (OpenAI-compatible speech, format_version 4, engine mode)

<p align="right"><strong>English</strong> · <a href="bundle_tts_standard.zh-CN.md">简体中文</a></p>

> **Category supplement.** The generic manifest, layout, entry, runtime, weights, and publishing rules remain authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) (zh: [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md)). This page adds only TTS-specific requirements.
>
> **Host-owned serving behavior.** In engine mode the host owns `/health`, `/v1/models`, `/v1/models/{id}`, authentication, the concurrency gate, request parsing, the error envelope, and the HTTP/SSE transport. These are defined in [bundle_serve_protocols.md](bundle_serve_protocols.md) (zh: [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)). A bundle must not reimplement host-owned routes; this page only defines what the TTS engine files and `ServeEngine.speech()` must do.
>
> **You will generate code.** Any script-mode bundle or self-hosted HTTP layer you were given is a reference for model maths only. Discard it and generate only the engine-mode files described here.

This standard is the acceptance contract for a publishable FlashCLI TTS bundle built from scratch for any TTS model. `model` is single-valued: one bundle serves one TTS model through one execution implementation. §9 contains reference implementations; §10 is the authoritative checklist. If any text conflicts with §10, §10 wins.

---

## 0. What you are building

The FlashCLI host terminates HTTP and calls the bundle's engine. A TTS bundle supplies model loading, synthesis, and audio encoding only:

| Host-owned (see [bundle_serve_protocols.md](bundle_serve_protocols.md)) | Bundle-owned |
|---|---|
| HTTP server, routes, authentication, request parsing | Model loading and inference |
| `/health`, `/v1/models`, `/v1/models/{id}` | `ServeEngine.model_id` |
| `POST /v1/audio/speech` JSON parsing | `ServeEngine.speech()` |
| Concurrency gate, error envelope, response headers, transport | `serve.py`, `engine.py`, `audio_encode.py` |
| Weight download according to the manifest | Reading the `checkpoint` path passed to `load()` |

So a TTS bundle is: **manifest + `serve.py` (`ServeEngine`) + `engine.py` (model maths) + `audio_encode.py`**.

---

## 1. Output tree (exactly this)

```text
<bundle>/
├── flashcli-bundle.json      # manifest, format_version 4      (§6)
├── serve.py                  # class ServeEngine                (§3, full reference in §9)
├── audio_encode.py           # response_format encoding         (§4, full reference in §9)
├── engine.py                 # model adapter                    (§5)
├── flash_rt/                 # optional, Python only, no .so
└── runtime/<env-key>/        # native .so, one dir per environment
```

Rules:

- Files at the bundle root are **public**: they are downloaded for every environment. Keep them small.
- Native `.so` files live only inside an environment's `runtime` directory. Never at the root, never in `flash_rt/`.
- Do **not** ship tests, docs, `*.md` (an optional short README aside), sample audio, caches, weights, build scripts, `__pycache__`, or `.pyc`.
- If a source tree already contains a self-hosted HTTP layer (its own FastAPI routes, `main()` + uvicorn, `FLASHCLI_CHECKPOINT` reading, response timing headers, or a `format_version: 3` manifest), discard it and generate the files above instead. Keep only the model maths.
- Do **not** write `run.py` (unless you also declare a `run` capability), `openai_compat.py`, uvicorn bootstrapping, or custom routes.

---

## 2. Hard prohibitions (self-check before finishing)

| # | Prohibited | Check |
|---|---|---|
| 1 | Bundle owns HTTP | `grep -n "uvicorn.run" serve.py` and `grep -n "FastAPI(" serve.py` → both 0 |
| 2 | Bundle declares routes | `grep -n "@app." *.py` and `grep -n "@router." *.py` → 0 |
| 3 | Reads host-internal env | no `FLASHCLI_RUNTIME_ID`, `FLASHCLI_IN_BUNDLE_VENV`, or host paths |
| 4 | Loads native libraries itself | no `ctypes` / `dlopen` of `.so` |
| 5 | Ships weights | no checkpoint files |
| 6 | Legacy manifest shape | no `variants` / `backends` / `entries` / top-level `runtime` / `format_version: 3` |
| 7 | `python-multipart` in dependencies | not needed (JSON only; audio arrives as a path) |
| 8 | Binaries in `flash_rt/` | Python sources only |
| 9 | Mutable weights revision | `weights.revision` must be a full 40-hex commit SHA |

---

## 3. `ServeEngine.speech` contract (host-facing)

`serve.py` MUST define the class named by `entry.serve.attr` (convention: `ServeEngine`) with:

```python
class ServeEngine:
    model_id: str                                                   # attribute or property
    def load(self, checkpoint: Path, preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def speech(self, request: SpeechRequest) -> SpeechResult: ...
```

Platform types are imported from the bundle package and must never be redefined:

```python
from flashcli_bundle.protocol import SpeechRequest, SpeechResult

# SpeechRequest(input, model, voice, response_format, speed, instructions, extras)
# SpeechResult(audio: bytes, media_type: str = "", usage: dict = {})
```

Field ownership:

| Request field | Parsed by the host into | Use in a TTS bundle |
|---|---|---|
| `input` | `request.input` | text to synthesize |
| `model` | `request.model` | ignore (single-model bundle) |
| `voice` | `request.voice` | ignore |
| `response_format` | `request.response_format` | `mp3` / `opus` / `aac` / `flac` / `wav` / `pcm` |
| `speed` | `request.speed` | 0.25–4.0, apply time-stretch |
| `instructions` | `request.instructions` | ignore (no style control in this bundle) |
| everything else | `request.extras` dict | **TTS extensions live here**: `reference_audio`, `reference_text`, `language` |

### 3.1 TTS extension fields

The host does **not** validate extension fields; `speech()` must.

| Extra | Required | Contract |
|---|---|---|
| `reference_audio` | yes | Absolute path to a reference clip; it must exist, be readable, and be at most 10 MiB |
| `reference_text` | yes | Transcript of the reference clip; non-empty and at most 2000 characters |
| `language` | yes | Language hint such as `zh`, `en`, or `auto`; non-empty |

Keep these checks in `speech()` even when a downstream model validates again, so clients get a stable `400` / `413` instead of a `500`.

### 3.2 Errors

| Situation | Raise | Client receives |
|---|---|---|
| Missing or invalid extension field, bad `response_format`, oversized input | `fastapi.HTTPException(status_code=400, detail="…")` | `400 {"detail": "…"}` |
| Reference clip larger than 10 MiB | `HTTPException(413, "…")` | `413 {"detail": "…"}` |
| Model or GPU failure | any other exception | `500 {"detail": "speech failed: …"}` |
| Malformed JSON body or non-object body | (not reached) | `422 {"detail": [{…}]}` — host validation |

The JSON error envelope is **host-defined**; do not promise `{"error": {...}}` in bundle docs. `/v1/models/{unknown}` returns the host's 404 object — nothing for the bundle to implement.

---

## 4. `audio_encode.py` contract

```python
def available_formats() -> list[str]: ...      # wav, flac, pcm [+ mp3, opus, aac when ffmpeg exists]
def encode(wav, response_format: str, speed: float = 1.0) -> tuple[bytes, str]:
    """Return (bytes, media_type). Source is 24 kHz mono float32."""
```

Requirements:

- Always produce **24 kHz mono** output. `pcm` is **headerless** s16le.
- `wav` / `flac` use `soundfile`. `mp3` / `opus` / `aac` use `ffmpeg` on `PATH` (`pipe:0` → `pipe:1`).
- Unknown format → `HTTPException(400, …)`. Missing ffmpeg for a compressed format → `HTTPException(400, …)` listing the formats that *are* available.
- `speed` uses pitch-preserving time-stretch (`librosa.effects.time_stretch`, `rate=speed`) and is skipped when `abs(speed - 1) < 1e-3`. Clamp to `0.25–4.0`.

---

## 5. `engine.py` contract (the only model-specific file)

```python
def load(checkpoint: Path, **options) -> None: ...      # weights → GPU (fp16) + runtime inject
def is_loaded() -> bool: ...
def synthesize(text: str, *, ref_audio: str, ref_text: str | None,
               language: str) -> "np.ndarray": ...      # 24 kHz mono float32
```

- `load()` is called once by the host **before** serving; keep it idempotent.
- `synthesize()` must NOT apply `speed` and must NOT encode audio.
- Fixed decoding parameters belong here as bundle constants, never as request fields:

```text
mode=clone · seed=42 · num_step=32 · guidance_scale=2.0 · position_temperature=5.0
denoise=True · preprocess_prompt=True · postprocess_output=True
```

- Model-level errors: raise plain exceptions (the host turns them into `500`).
- No `fastapi` / `uvicorn` / `starlette` imports here.

The Python engine contract follows the `python` backend in [bundle_execution_abi.md](bundle_execution_abi.md) §5.

---

## 6. Manifest requirements (TTS-specific)

The full schema is authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) §3. A TTS bundle's `defaults` must contain at least:

```json
"defaults": {
  "entry": {
    "serve": {
      "kind": "python",
      "module": "serve",
      "attr": "ServeEngine",
      "mode": "engine",
      "capabilities": ["openai.audio.speech"],
      "concurrency": 1
    }
  },
  "python_abi": "312",
  "python_dependencies": {
    "torch": { "package": "torch==<ver>", "index": "<130>" },
    "pip": ["numpy", "soundfile", "librosa", "fastapi", "<model-package>"]
  },
  "env": { "FLASHRT_EAGER_CODEC": "1" },
  "resources": { "min_vram_mib": 12288 },
  "weights": {
    "source": "huggingface",
    "repo": "<org>/<model>",
    "revision": "<40-hex commit sha>"
  }
}
```

Rules:

1. `format_version` is **4** and `protocol_version` is **1**.
2. `entry.serve` uses `kind: "python"`, `mode: "engine"`, `attr: "ServeEngine"`; the module file must exist.
3. `capabilities` is exactly `["openai.audio.speech"]`. Never add chat capabilities (they would require `chat` / `chat_stream`); `[]` would expose no speech route at all.
4. `concurrency: 1` for a synchronous `speech()`. The host owns the gate; do not add locks in the bundle. `N > 1` requires async gated methods.
5. `weights.revision` (and any `extra_weights.*.revision`) is a full 40-hex SHA; branches and tags are rejected.
6. `env` is the only way to declare bundle-level environment variables in engine mode. Never read `FLASHCLI_CHECKPOINT` — that is script mode.
7. `resources.min_vram_mib` uses the measured peak with a small margin (peak 11.4 GiB → `12288`).
8. Do not list `flashcli-bundle` (or `flashcli`) in `pip`: the host installs the platform package itself. `pydantic` / `uvicorn` are not needed because the host owns request models and the server. Do not add `python-multipart`.
9. `environments` must be non-empty; `python_abi` must match the `-py{PY}` suffix of every environment key, and every declared `runtime` directory must exist (a pure-Python/CPU environment may omit `runtime`). See [bundle_publish_standard.md](bundle_publish_standard.md) §3.9.
10. `build.sources[]` is written by `pack` into `dist/flashcli-bundle.json`; do not hand-write it.

---

## 7. Native artifacts

```text
runtime/<env-key>/
└── {module_base}-{flashrt_abi}-{build_tag}.so     # e.g. flash_rt_kernels-...-sm120-....so
```

- The host registers each `.so` as an extension module by `module_base` **before** importing the entry.
- Do not hardcode environment keys inside filenames; do not place `.so` files at the root or in `flash_rt/`.
- `flash_rt/` (if shipped) contains Python only; it is either public (bundle root) or per-environment (inside a runtime directory).
- Native entry kinds and their ABI versions are defined in [bundle_execution_abi.md](bundle_execution_abi.md) §6–§7.

---

## 8. Build → pack → validate

```bash
# 1) Author tree: manifest + serve.py + audio_encode.py + engine.py (+ flash_rt/ + runtime/)
# 2) Static validation
flashcli bundle validate <bundle-root-or-dist>

# 3) Host smoke (the host runs HTTP; the bundle only supplies the engine)
flashcli serve <bundle-root> &        # or: flashcli serve flashcli-bundle/<name>:<version>
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 1; done
curl -s -X POST localhost:8000/v1/audio/speech -H 'Content-Type: application/json' -d '{
  "input":"hello",
  "reference_audio":"/abs/ref.wav",
  "reference_text":"hello",
  "language":"en",
  "response_format":"wav"}' -o /tmp/t.wav -w '%{http_code}\n'
file /tmp/t.wav                    # RIFF, 24000 Hz, mono
```

Expected error smoke (all from **your** `speech()` validation):

```bash
# missing reference_audio  -> 400 {"detail": "reference_audio is required (absolute path)"}
# relative path            -> 400 {"detail": "reference_audio must be an absolute path"}
# missing file             -> 400 {"detail": "reference_audio not found: …"}
# >10 MiB                  -> 413 {"detail": "reference_audio exceeds 10 MiB"}
```

`pack` (maintainer side) copies only the release set and the selected runtime unit into `dist/`, and merges `build.sources[]` into `dist/flashcli-bundle.json`. Upload `dist/` as the new FlashHub version, then confirm the version endpoint returns the complete `files[]`, including `.so` URLs under `runtime/` subdirectories. Publishing rules are authoritative in [bundle_publish_standard.md](bundle_publish_standard.md) §2.

---

## 9. Reference implementations (copy verbatim, then fill in model maths)

### 9.1 `serve.py`

```python
"""ServeEngine for <model>. The host owns HTTP; this module only implements the engine contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException
from flashcli_bundle.protocol import SpeechRequest, SpeechResult

import audio_encode
import engine

MAX_INPUT_CHARS = 4096
REF_TEXT_MAX = 2000
REF_MAX_MB = 10


class ServeEngine:
    """Host-loaded engine: load → warmup → speech()."""

    model_id = "<model>_flashrt"

    # -- lifecycle -------------------------------------------------------
    def load(self, checkpoint: Path, preset: Any = None, **options: Any) -> None:
        engine.load(checkpoint, **options)

    def warmup(self, spec: Optional[str] = None) -> None:
        warm = getattr(engine, "warmup", None)
        if callable(warm):
            warm()

    # -- inference -------------------------------------------------------
    def speech(self, request: SpeechRequest) -> SpeechResult:
        text = request.input
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(400, f"input exceeds {MAX_INPUT_CHARS} characters")

        extras = request.extras or {}
        ref_audio = str(extras.get("reference_audio") or "").strip()
        ref_text = str(extras.get("reference_text") or "").strip()
        language = str(extras.get("language") or "").strip()

        if not ref_audio:
            raise HTTPException(400, "reference_audio is required (absolute path)")
        path = Path(ref_audio)
        if not path.is_absolute():
            raise HTTPException(400, "reference_audio must be an absolute path")
        if not path.is_file():
            raise HTTPException(400, f"reference_audio not found: {path}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise HTTPException(400, f"reference_audio is unreadable: {exc}") from exc
        if size > REF_MAX_MB * 1024 * 1024:
            raise HTTPException(413, f"reference_audio exceeds {REF_MAX_MB} MiB")

        if not ref_text:
            raise HTTPException(400, "reference_text is required")
        if len(ref_text) > REF_TEXT_MAX:
            raise HTTPException(400, f"reference_text must be at most {REF_TEXT_MAX} characters")
        if not language:
            raise HTTPException(400, "language is required (e.g. zh / en / auto)")

        wav = engine.synthesize(text, ref_audio=str(path), ref_text=ref_text,
                                language=language)
        audio, media_type = audio_encode.encode(wav, request.response_format, request.speed)
        return SpeechResult(audio=audio, media_type=media_type)
```

### 9.2 `audio_encode.py`

```python
"""Encode a 24 kHz mono float32 waveform into an OpenAI response_format."""
from __future__ import annotations

import io
import shutil
import subprocess
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import HTTPException

SAMPLE_RATE = 24000

_FFMPEG_FORMATS = {
    "mp3": (["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3"], "audio/mpeg"),
    "opus": (["-c:a", "libopus", "-b:a", "48k", "-f", "ogg"], "audio/ogg"),
    "aac": (["-c:a", "aac", "-b:a", "128k", "-f", "adts"], "audio/aac"),
}


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def available_formats() -> list[str]:
    formats = ["wav", "flac", "pcm"]
    if _ffmpeg():
        formats.extend(_FFMPEG_FORMATS)
    return formats


def _mono(audio: Any) -> np.ndarray:
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    if peak > 1.0:
        a = a / peak
    return np.clip(a, -1.0, 1.0)


def _stretch(audio: np.ndarray, speed: float) -> np.ndarray:
    if abs(speed - 1.0) < 1e-3 or audio.size == 0:
        return audio
    import librosa

    rate = float(min(4.0, max(0.25, speed)))
    return librosa.effects.time_stretch(audio, rate=rate).astype(np.float32, copy=False)


def encode(wav: Any, response_format: str = "mp3",
           speed: float = 1.0) -> tuple[bytes, str]:
    a = _stretch(_mono(wav), speed)
    fmt = (response_format or "mp3").lower()

    if fmt == "pcm":
        return (a * 32767.0).astype("<i2").tobytes(), "audio/pcm"

    if fmt in ("wav", "flac"):
        buf = io.BytesIO()
        sf.write(buf, a, SAMPLE_RATE, format=fmt.upper(), subtype="PCM_16")
        return buf.getvalue(), f"audio/{fmt}"

    if fmt not in _FFMPEG_FORMATS:
        raise HTTPException(
            400, f"Invalid response_format '{fmt}'. Supported: {', '.join(available_formats())}")

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        raise HTTPException(
            400, f"response_format '{fmt}' needs ffmpeg. Use one of: wav, flac, pcm")

    args, media_type = _FFMPEG_FORMATS[fmt]
    wav_bytes = io.BytesIO()
    sf.write(wav_bytes, a, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
        input=wav_bytes.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=300, check=False)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + proc.stderr.decode(errors="replace")[:400])
    return proc.stdout, media_type
```

### 9.3 `engine.py` (fill the three TODOs)

```python
"""Model adapter. The only model-specific module of the bundle."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

_model = None

NUM_STEPS = 32
GUIDANCE_SCALE = 2.0
POSITION_TEMPERATURE = 5.0
DEFAULT_SEED = 42


def load(checkpoint: Path, **options) -> None:
    global _model
    if _model is not None:
        return
    # TODO(1): build the model in fp16 on cuda:0 and inject the native runtime, e.g.
    #   import torch
    #   from mymodel import Model
    #   m = Model.from_pretrained(str(checkpoint), device_map="cuda:0", dtype=torch.float16).eval()
    #   import flash_rt; flash_rt.inject(m)
    #   _model = m
    raise NotImplementedError


def is_loaded() -> bool:
    return _model is not None


def synthesize(text: str, *, ref_audio: str, ref_text: Optional[str],
               language: str) -> np.ndarray:
    if _model is None:
        raise RuntimeError("engine not loaded")
    # TODO(2): build conditioning from ref_audio / ref_text
    # TODO(3): generate and return a 24 kHz mono float32 waveform
    raise NotImplementedError
```

---

## 10. Acceptance checklist (authoritative)

- [ ] Tree = §1 exactly; no tests/docs/caches/weights/build scripts
- [ ] `flashcli-bundle.json` at the root; `format_version: 4`, `protocol_version: 1`
- [ ] `defaults` present; `environments` non-empty; no `variants` / `backends` / `entries` / top-level `runtime`
- [ ] `entry.serve`: `kind: python`, `mode: engine`, `module: serve`, `attr: ServeEngine`
- [ ] `capabilities` = `["openai.audio.speech"]`; `concurrency: 1`
- [ ] `python_abi` matches the `-py{PY}` suffix of every environment key
- [ ] `python_dependencies.pip` includes `fastapi` / `soundfile` / `librosa` and the model package; excludes `python-multipart`
- [ ] `.so` only inside runtime directories; `flash_rt/` contains Python only
- [ ] `weights.revision` (and any `extra_weights.*.revision`) = 40-hex SHA
- [ ] `resources.min_vram_mib` set from a measured peak (recommended)
- [ ] every non-empty `environments.<key>.runtime` directory exists; a **pure-Python/CPU environment may omit `runtime`**
- [ ] if a runtime directory contains `.so`, filenames are recognizable as extension modules (`{module_base}-…so`)
- [ ] no ambiguous fallback entries: exact environment keys first; fallbacks (if any) must differ by `os` / `arch` / `python_abi` / `vendor` / `sm` / `cuda`
- [ ] files that must not be shared live inside the owning environment's runtime directory; everything else is public
- [ ] `flash_rt/` (if shipped) contains **only modules reachable from the entry** (no unused model or frontend code)
- [ ] uploaded version returns the complete `files[]`, including `.so` URLs under subdirectories
- [ ] `ServeEngine` implements `model_id`, `load`, `warmup`, `speech`
- [ ] `speech()` reads `reference_audio` / `reference_text` / `language` from `request.extras`
- [ ] `speech()` validates: absolute path, exists, ≤10 MiB, `reference_text` ≤2000, `language` non-empty
- [ ] `speech()` applies `speed` and returns `SpeechResult(audio, media_type)`
- [ ] no `uvicorn` / `FastAPI(` / `@app.` / `@router.` / `ctypes` in the bundle
- [ ] `flashcli bundle validate <tree>` passes
- [ ] smoke: `/v1/models` 200 → speech 200 → `wav` is 24 kHz mono
- [ ] error smoke: missing/relative/missing-file reference → 400; >10 MiB → 413
- [ ] `dist/flashcli-bundle.json` contains `build.sources[]`, identical for all environments

---

## 11. Model adaptation table

| Model | `load()` | `synthesize()` notes |
|---|---|---|
| OmniVoice | `from_pretrained` fp16 + FlashRT inject | `create_voice_clone_prompt(ref_audio, ref_text)` → `generate(voice_clone_prompt=…)` |
| Chatterbox | multilingual weights | reference clip as speaker prompt |
| CosyVoice | CosyVoice + vocoder | `inference_zero_shot(text, ref_text, ref_audio)` |
| Qwen3-TTS | Base vs CustomVoice | cloning via Base; style via CustomVoice |
| Piper / Kokoro | onnx + voice config | no cloning → `HTTPException(400, "… does not support reference cloning")` |

All of them: 24 kHz mono `float32` out of `synthesize()`; `speed` and encoding stay outside `engine.py`.
