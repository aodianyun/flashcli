# TTS Bundle 标准（OpenAI 兼容语音合成，format_version 4，engine 模式）

<p align="right"><a href="bundle_tts_standard.md">English</a> · <strong>简体中文</strong></p>

> **分类补充规范。** 通用 manifest、目录、entry、运行时、权重与发布规则仍以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) 为准（英文：[bundle_publish_standard.md](bundle_publish_standard.md)）。本文只补充 TTS 特有要求。
>
> **宿主负责的服务行为。** engine 模式下，host 基础路由（health、models）、鉴权、并发门控、请求解析、错误封装以及 HTTP/SSE 传输均由宿主负责，定义见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)（英文：[bundle_serve_protocols.md](bundle_serve_protocols.md)）。bundle 不得重新实现宿主路由；本文只规定 TTS 引擎文件与 `ServeEngine.speech()` 必须完成的工作。
>
> **你需要生成代码。** 已拿到的 script 模式 bundle 或自带 HTTP 层只能作为模型数学的参考；请丢弃它们，只生成本文描述的 engine 模式文件。

本规范是面向任意 TTS 模型从零构建可发布 FlashCLI TTS bundle 的验收契约。`model` 为单值：一个 bundle 通过一套执行实现服务一个 TTS 模型。§9 提供参考实现；§10 是权威清单。若其他文字与 §10 冲突，以 §10 为准。

---

## 0. 构建目标

FlashCLI 宿主负责终止 HTTP 并调用 bundle 引擎。TTS bundle 只提供模型加载、语音合成与音频编码：

| 宿主负责（见 [bundle_serve_protocols.zh-CN.md](bundle_serve_protocols.zh-CN.md)） | Bundle 负责 |
|---|---|
| HTTP 服务、路由、鉴权、请求解析 | 模型加载与推理 |
| host 基础路由（health、models） | `ServeEngine.model_id` |
| `POST /v1/audio/speech` 的 JSON 解析 | `ServeEngine.speech()` |
| 并发门控、错误封装、响应头、传输 | `serve.py`、`engine.py`、`audio_encode.py` |
| 按 manifest 下载权重 | 使用传给 `load()` 的 `checkpoint` 路径 |

因此，一个 TTS bundle 由 **manifest + `serve.py`（`ServeEngine`）+ `engine.py`（模型数学）+ `audio_encode.py`** 组成。

---

## 1. 输出目录树（严格一致）

```text
<bundle>/
├── flashcli-bundle.json      # manifest，format_version 4      （§6）
├── serve.py                  # class ServeEngine                （§3，完整参考见 §9）
├── audio_encode.py           # response_format 编码             （§4，完整参考见 §9）
├── engine.py                 # 模型适配层                       （§5）
├── flash_rt/                 # 可选，仅 Python，不得含 .so
└── runtime/<env-key>/        # native .so，每个环境一个目录
```

规则：

- bundle 根目录下的文件是**公共文件**：每个环境都会下载。保持它们体积小。
- native `.so` 只能放在某个环境的 `runtime` 目录内。不得放在根目录，也不得放在 `flash_rt/`。
- **不要**发布测试、文档、`*.md`（可选的简短 README 除外）、示例音频、缓存、权重、构建脚本、`__pycache__` 或 `.pyc`。
- 如果源目录已包含自建 HTTP 层（自己的 FastAPI 路由、`main()` + uvicorn、读取 `FLASHCLI_CHECKPOINT`、响应计时头，或 `format_version: 3` manifest），请丢弃它，改为生成上面的文件；只保留模型数学。
- **不要**编写 `run.py`（除非同时声明 `run` capability）、`openai_compat.py`、uvicorn 启动代码或自定义路由。

---

## 2. 硬性禁止项（完成前自检）

| # | 禁止 | 检查 |
|---|---|---|
| 1 | Bundle 自持 HTTP | `grep -n "uvicorn.run" serve.py` 与 `grep -n "FastAPI(" serve.py` → 均为 0 |
| 2 | Bundle 声明路由 | `grep -n "@app." *.py` 与 `grep -n "@router." *.py` → 为 0 |
| 3 | 读取宿主内部环境变量 | 不得出现 `FLASHCLI_RUNTIME_ID`、`FLASHCLI_IN_BUNDLE_VENV` 或宿主路径 |
| 4 | 自行加载 native 库 | 不得对 `.so` 使用 `ctypes` / `dlopen` |
| 5 | 携带权重 | 不得包含 checkpoint 文件 |
| 6 | 旧版 manifest 结构 | 不得出现 `variants` / `backends` / `entries` / 顶层 `runtime` / `format_version: 3` |
| 7 | 依赖中包含 `python-multipart` | 不需要（仅 JSON；音频以路径传入） |
| 8 | `flash_rt/` 中放二进制 | 只能放 Python 源码 |
| 9 | 权重 revision 可变 | `weights.revision` 必须是完整 40 位十六进制 commit SHA |

---

## 3. `ServeEngine.speech` 契约（面向宿主）

`serve.py` 必须定义 `entry.serve.attr` 指定的类（约定为 `ServeEngine`），并提供：

```python
class ServeEngine:
    model_id: str                                                   # attribute or property
    def load(self, checkpoint: Path, preset, **options) -> None: ...
    def warmup(self, spec: str | None) -> None: ...
    def speech(self, request: SpeechRequest) -> SpeechResult: ...
```

平台类型从 bundle 包导入，不得重新定义：

```python
from flashcli_bundle.protocol import SpeechRequest, SpeechResult

# SpeechRequest(input, model, voice, response_format, speed, instructions, extras)
# SpeechResult(audio: bytes, media_type: str = "", usage: dict = {})
```

字段归属：

| 请求字段 | 宿主解析到 | 在 TTS bundle 中的用途 |
|---|---|---|
| `input` | `request.input` | 待合成文本 |
| `model` | `request.model` | 忽略（单模型 bundle） |
| `voice` | `request.voice` | 忽略 |
| `response_format` | `request.response_format` | `mp3` / `opus` / `aac` / `flac` / `wav` / `pcm` |
| `speed` | `request.speed` | 0.25–4.0，执行时间伸缩 |
| `instructions` | `request.instructions` | 忽略（本 bundle 不支持风格控制） |
| 其余全部 | `request.extras` 字典 | **TTS 扩展字段在这里**：`reference_audio`、`reference_text`、`language` |

### 3.1 TTS 扩展字段

宿主**不**校验扩展字段；由 `speech()` 负责。

| 扩展字段 | 必填 | 契约 |
|---|---|---|
| `reference_audio` | 是 | 参考音频的绝对路径；文件必须存在、可读，且不超过 10 MiB |
| `reference_text` | 是 | 参考音频的转写文本；非空且不超过 2000 个字符 |
| `language` | 是 | 语言提示，例如 `zh`、`en`、`auto`；非空 |

即使下游模型会再次校验，也要在 `speech()` 中保留这些检查，让客户端得到稳定的 `400` / `413`，而不是 `500`。

### 3.2 错误

| 情况 | 抛出 | 客户端收到 |
|---|---|---|
| 扩展字段缺失或非法、`response_format` 非法、输入过长 | `fastapi.HTTPException(status_code=400, detail="…")` | `400 {"detail": "…"}` |
| 参考音频大于 10 MiB | `HTTPException(413, "…")` | `413 {"detail": "…"}` |
| 模型 / GPU 失败 | 其他任意异常 | `500 {"detail": "speech failed: …"}` |
| JSON 请求体格式错误或不是对象 | （不会到达此处） | `422 {"detail": [{…}]}` — 宿主校验 |

JSON 错误封装由**宿主定义**；不要在 bundle 文档中承诺 `{"error": {...}}`。未知模型的 404 属于宿主行为，bundle 无需实现。

---

## 4. `audio_encode.py` 契约

```python
def available_formats() -> list[str]: ...      # wav, flac, pcm [+ mp3, opus, aac when ffmpeg exists]
def encode(wav, response_format: str, speed: float = 1.0) -> tuple[bytes, str]:
    """Return (bytes, media_type). Source is 24 kHz mono float32."""
```

要求：

- 始终输出 **24 kHz 单声道**。`pcm` 为**无文件头**的 s16le。
- `wav` / `flac` 使用 `soundfile`。`mp3` / `opus` / `aac` 使用 `PATH` 上的 `ffmpeg`（`pipe:0` → `pipe:1`）。
- 未知格式 → `HTTPException(400, …)`。压缩格式缺少 ffmpeg → `HTTPException(400, …)`，并列出*当前可用*的格式。
- `speed` 使用保持音高的时间伸缩（`librosa.effects.time_stretch`，`rate=speed`），当 `abs(speed - 1) < 1e-3` 时跳过。限制在 `0.25–4.0`。

---

## 5. `engine.py` 契约（唯一的模型相关文件）

```python
def load(checkpoint: Path, **options) -> None: ...      # weights → GPU (fp16) + runtime inject
def is_loaded() -> bool: ...
def synthesize(text: str, *, ref_audio: str, ref_text: str | None,
               language: str) -> "np.ndarray": ...      # 24 kHz mono float32
```

- `load()` 由宿主在开始服务**之前**调用一次；必须保持幂等。
- `synthesize()` 不得应用 `speed`，也不得编码音频。
- 固定解码参数属于此文件，作为 bundle 常量，绝不能作为请求字段：

```text
mode=clone · seed=42 · num_step=32 · guidance_scale=2.0 · position_temperature=5.0
denoise=True · preprocess_prompt=True · postprocess_output=True
```

- 模型层错误：抛出普通异常（宿主会转换为 `500`）。
- 此文件不得导入 `fastapi` / `uvicorn` / `starlette`。

Python 引擎契约遵循 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) §5 的 `python` 后端。

---

## 6. Manifest 要求（TTS 特有）

完整 schema 以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) §3 为准。TTS bundle 的 `defaults` 至少包含：

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

规则：

1. `format_version` 为 **4**，`protocol_version` 为 **1**。
2. `entry.serve` 使用 `kind: "python"`、`mode: "engine"`、`attr: "ServeEngine"`；模块文件必须存在。
3. `capabilities` 必须恰好为 `["openai.audio.speech"]`。不得加入 chat 能力（那会要求 `chat` / `chat_stream`）；写成 `[]` 则完全不会暴露语音路由。
4. 同步 `speech()` 使用 `concurrency: 1`。并发门控由宿主负责，bundle 中不要加锁。`N > 1` 要求异步门控方法。
5. `weights.revision`（以及任何 `extra_weights.*.revision`）必须是完整 40 位十六进制 SHA；拒绝分支名和标签。
6. `env` 是 engine 模式下声明 bundle 级环境变量的唯一方式。绝不能读取 `FLASHCLI_CHECKPOINT`——那是 script 模式。
7. `resources.min_vram_mib` 使用实测峰值加少量余量（峰值 11.4 GiB → `12288`）。
8. 不要在 `pip` 中列出 `flashcli-bundle`（或 `flashcli`）：宿主会自行安装平台包。`pydantic` / `uvicorn` 也不需要，因为请求模型和服务端由宿主负责。不要添加 `python-multipart`。
9. `environments` 必须非空；`python_abi` 必须与每个环境 key 的 `-py{PY}` 后缀一致，且每个声明的 `runtime` 目录都必须存在（纯 Python/CPU 环境可以省略 `runtime`）。见 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) §3.9。
10. `build.sources[]` 由 `pack` 写入 `dist/flashcli-bundle.json`；不要手写。

---

## 7. Native 产物

```text
runtime/<env-key>/
└── {module_base}-{flashrt_abi}-{build_tag}.so     # e.g. flash_rt_kernels-...-sm120-....so
```

- 宿主会在导入 entry **之前**按 `module_base` 将每个 `.so` 注册为扩展模块。
- 不要在文件名中硬编码环境 key；不要把 `.so` 放在根目录或 `flash_rt/`。
- `flash_rt/`（如发布）只能包含 Python；它要么是公共的（bundle 根目录），要么属于某个环境（放在该环境的 runtime 目录内）。
- native entry 类型及其 ABI 版本定义见 [bundle_execution_abi.zh-CN.md](bundle_execution_abi.zh-CN.md) §6–§7。

---

## 8. 构建 → 打包 → 校验

```bash
# 1) Author tree: manifest + serve.py + audio_encode.py + engine.py (+ flash_rt/ + runtime/)
# 2) Static validation
flashcli bundle validate <bundle-root-or-dist>

# 3) Host smoke (the host runs HTTP; the bundle only supplies the engine)
flashcli serve <bundle-root> &        # or: flashcli serve flashcli-bundle/<name>:<version>
# 等待 host 就绪（host 持有该路由，见 bundle_serve_protocols.zh-CN.md）
until curl -sf localhost:8000/health >/dev/null; do sleep 1; done
curl -s -X POST localhost:8000/v1/audio/speech -H 'Content-Type: application/json' -d '{
  "input":"hello",
  "reference_audio":"/abs/ref.wav",
  "reference_text":"hello",
  "language":"en",
  "response_format":"wav"}' -o /tmp/t.wav -w '%{http_code}\n'
file /tmp/t.wav                    # RIFF, 24000 Hz, mono
```

预期错误冒烟（全部来自**你自己的** `speech()` 校验）：

```bash
# missing reference_audio  -> 400 {"detail": "reference_audio is required (absolute path)"}
# relative path            -> 400 {"detail": "reference_audio must be an absolute path"}
# missing file             -> 400 {"detail": "reference_audio not found: …"}
# >10 MiB                  -> 413 {"detail": "reference_audio exceeds 10 MiB"}
```

`pack`（维护者侧）只把发布文件集和选定的 runtime 单元复制到 `dist/`，并把 `build.sources[]` 合并进 `dist/flashcli-bundle.json`。将 `dist/` 作为新的 FlashHub 版本上传，然后确认版本端点返回完整的 `files[]`，包括 `runtime/` 子目录下的 `.so` URL。发布规则以 [bundle_publish_standard.zh-CN.md](bundle_publish_standard.zh-CN.md) §2 为准。

---

## 9. 参考实现（原样复制，再填入模型数学）

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

### 9.3 `engine.py`（填入三个 TODO）

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

## 10. 验收清单（权威）

- [ ] 目录树与 §1 完全一致；无测试/文档/缓存/权重/构建脚本
- [ ] `flashcli-bundle.json` 位于根目录；`format_version: 4`、`protocol_version: 1`
- [ ] 存在 `defaults`；`environments` 非空；无 `variants` / `backends` / `entries` / 顶层 `runtime`
- [ ] `entry.serve`：`kind: python`、`mode: engine`、`module: serve`、`attr: ServeEngine`
- [ ] `capabilities` = `["openai.audio.speech"]`；`concurrency: 1`
- [ ] `python_abi` 与每个环境 key 的 `-py{PY}` 后缀一致
- [ ] `python_dependencies.pip` 包含 `fastapi` / `soundfile` / `librosa` 与模型包；不包含 `python-multipart`
- [ ] `.so` 只在 runtime 目录内；`flash_rt/` 只含 Python
- [ ] `weights.revision`（以及任何 `extra_weights.*.revision`）= 40 位十六进制 SHA
- [ ] `resources.min_vram_mib` 按实测峰值设置（推荐）
- [ ] 每个非空的 `environments.<key>.runtime` 目录都存在；**纯 Python/CPU 环境可以省略 `runtime`**
- [ ] 如果 runtime 目录包含 `.so`，文件名应能识别为扩展模块（`{module_base}-…so`）
- [ ] 无歧义 fallback 条目：优先精确环境 key；fallback（如有）必须按 `os` / `arch` / `python_abi` / `vendor` / `sm` / `cuda` 区分
- [ ] 不可共享的文件放在所属环境的 runtime 目录内；其余文件均为公共文件
- [ ] `flash_rt/`（如发布）**只包含从 entry 可达的模块**（无未使用的模型或前端代码）
- [ ] 上传后的版本返回完整 `files[]`，包括子目录下的 `.so` URL
- [ ] `ServeEngine` 实现 `model_id`、`load`、`warmup`、`speech`
- [ ] `speech()` 从 `request.extras` 读取 `reference_audio` / `reference_text` / `language`
- [ ] `speech()` 校验：绝对路径、文件存在、≤10 MiB、`reference_text` ≤2000、`language` 非空
- [ ] `speech()` 应用 `speed` 并返回 `SpeechResult(audio, media_type)`
- [ ] bundle 中无 `uvicorn` / `FastAPI(` / `@app.` / `@router.` / `ctypes`
- [ ] `flashcli bundle validate <tree>` 通过
- [ ] 冒烟：host 就绪 200 → speech 200 → `wav` 为 24 kHz 单声道
- [ ] 错误冒烟：reference 缺失/相对路径/文件不存在 → 400；>10 MiB → 413
- [ ] `dist/flashcli-bundle.json` 包含 `build.sources[]`，且所有环境一致

---

## 11. 模型适配表

| 模型 | `load()` | `synthesize()` 说明 |
|---|---|---|
| OmniVoice | `from_pretrained` fp16 + FlashRT inject | `create_voice_clone_prompt(ref_audio, ref_text)` → `generate(voice_clone_prompt=…)` |
| Chatterbox | 多语言权重 | 将参考音频作为说话人提示 |
| CosyVoice | CosyVoice + vocoder | `inference_zero_shot(text, ref_text, ref_audio)` |
| Qwen3-TTS | Base 与 CustomVoice | 通过 Base 做克隆；通过 CustomVoice 做风格 |
| Piper / Kokoro | onnx + 音色配置 | 不支持克隆 → `HTTPException(400, "… does not support reference cloning")` |

以上所有模型：`synthesize()` 输出 24 kHz 单声道 `float32`；`speed` 与编码都在 `engine.py` 之外处理。
