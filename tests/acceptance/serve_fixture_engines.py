"""Deterministic-but-realistic ServeEngine fixtures per modality.

Each class models the public behavior of the corresponding mature service
family (OpenAI-compatible chat/embedding/moderation, Whisper-like ASR,
TTS audio, image generation, asynchronous video jobs, code completion) so the
host protocol surface can be exercised with realistic inputs and outputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import time
from typing import Any

from flashcli_bundle.protocol import (
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    ChatChunk,
    ChatRequest,
    ChatResult,
    EmbeddingRequest,
    EmbeddingResult,
    ImageGenerationRequest,
    ImageGenerationResult,
    ModerationRequest,
    ModerationResult,
    SpeechRequest,
    SpeechResult,
    VideoRequest,
)

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f8cf000003010100c9fe92ef0000000049454e44ae426082"
)

AUDIO_MEDIA = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

AUDIO_MAGIC = {
    "mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00",
    "opus": b"OggS",
    "aac": b"\xff\xf1",
    "flac": b"fLaC",
    "pcm": b"\x00\x00",
}

VIDEO_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 16


def _last_user_text(messages) -> str:  # noqa: ANN001
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind in ("text", "input_text", "output_text"):
                    parts.append(str(part.get("text", "")))
                elif kind in ("input_audio", "audio") and part.get("transcript"):
                    parts.append(str(part["transcript"]))
            return " ".join(parts)
    return ""


def _usage(prompt: str, completion: str) -> dict[str, int]:
    prompt_tokens = max(1, len(prompt.split()))
    completion_tokens = max(1, len(completion.split()))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _tool_call(request: ChatRequest) -> dict[str, Any]:
    name = "get_weather"
    tools = request.tools or []
    first = tools[0] if tools else None
    if isinstance(first, dict):
        function = first.get("function") if isinstance(first.get("function"), dict) else first
        if isinstance(function, dict) and function.get("name"):
            name = str(function["name"])
    return {
        "id": "call_weather",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps({"city": "Beijing"})},
    }


def _wants_tool(request: ChatRequest) -> bool:
    text = _last_user_text(request.messages).lower()
    return bool(request.tools) and ("weather" in text or "tool" in text)


def _wav_bytes(text: str) -> bytes:
    sample_rate = 8000
    duration = max(0.1, min(0.5, len(text) * 0.02))
    samples = int(sample_rate * duration)
    data = b"".join(struct.pack("<h", 0) for _ in range(samples))
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


class LLMEngine:
    model_id = "llm-fixture"

    def __init__(self) -> None:
        self.last: ChatRequest | None = None

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None = None) -> None:
        pass

    def register_routes(self, app) -> None:  # noqa: ANN001
        engine = self

        @app.get("/debug/last")
        async def debug_last() -> dict[str, Any]:
            req = engine.last
            if req is None:
                return {"last": None}
            return {
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "tool_calls": m.tool_calls,
                        "tool_call_id": m.tool_call_id,
                        "reasoning_content": m.reasoning_content,
                    }
                    for m in req.messages
                ],
                "extras": req.extras,
                "tools": req.tools,
                "max_tokens": req.max_tokens,
                "temperature": req.temperature,
                "stop": req.stop,
            }

    def chat(self, request: ChatRequest) -> ChatResult:
        self.last = request
        prompt = _last_user_text(request.messages)
        if _wants_tool(request):
            content = "I'll check the weather."
            usage = _usage(prompt, content)
            return ChatResult(
                content=content,
                reasoning_content="The user asked for a tool-backed fact.",
                finish_reason="tool_calls",
                usage={**usage, "total_tokens": usage["total_tokens"]},
                tool_calls=[_tool_call(request)],
            )
        content = f"Answer: {prompt or 'hello'}"
        return ChatResult(
            content=content,
            reasoning_content="Considering the request.",
            finish_reason="stop",
            usage=_usage(prompt, content),
        )

    def chat_stream(self, request: ChatRequest):
        self.last = request
        prompt = _last_user_text(request.messages)
        if _wants_tool(request):
            content = "I'll check the weather."
            yield ChatChunk(reasoning_delta="The user asked for a tool-backed fact. ")
            for word in content.split(" "):
                yield ChatChunk(content_delta=word + " ")
            usage = _usage(prompt, content)
            yield ChatChunk(
                tool_calls=[_tool_call(request)],
                finish_reason="tool_calls",
                usage=usage,
            )
            return
        content = f"Answer: {prompt or 'hello'}"
        yield ChatChunk(reasoning_delta="Considering the request. ")
        for word in content.split(" "):
            yield ChatChunk(content_delta=word + " ")
        yield ChatChunk(finish_reason="stop", usage=_usage(prompt, content))

    def count_tokens(self, request: ChatRequest) -> int:
        text = " ".join(_last_user_text([m]) for m in request.messages)
        return max(1, len(text.split()) + len(request.messages))

    def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        return AudioTranscriptionResult(
            text="Hello from realtime audio.",
            language="en",
            duration=1.0,
            segments=[{"id": 0, "start": 0.0, "end": 1.0, "text": "Hello from realtime audio."}],
            words=[],
            usage={"total_tokens": 4},
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        embeddings: list[list[float]] = []
        for item in request.input:
            text = item if isinstance(item, str) else " ".join(str(t) for t in item)
            digest = hashlib.sha256(text.encode("utf-8")).digest()[:8]
            embeddings.append([round(byte / 255.0, 6) for byte in digest])
        return EmbeddingResult(
            embeddings=embeddings,
            usage={
                "prompt_tokens": len(request.input),
                "total_tokens": len(request.input),
            },
        )

    def moderate(self, request: ModerationRequest) -> ModerationResult:
        keywords = ("violence", "hate", "harassment", "bad")
        results = []
        for text in request.input:
            flagged = any(word in text.lower() for word in keywords)
            results.append(
                {
                    "flagged": flagged,
                    "categories": {"violence": flagged},
                    "category_scores": {"violence": 1.0 if flagged else 0.0},
                }
            )
        return ModerationResult(
            results=results, usage={"total_tokens": len(request.input)}
        )


class AsyncLLMEngine(LLMEngine):
    """Async chat engine used to exercise serve.concurrency > 1."""

    model_id = "async-fixture"

    async def chat(self, request: ChatRequest) -> ChatResult:
        await asyncio.sleep(0.3)
        return super().chat(request)

    async def chat_stream(self, request: ChatRequest):
        for chunk in super().chat_stream(request):
            yield chunk


class CodeEngine(LLMEngine):
    model_id = "code-fixture"

    def _code(self, prompt: str) -> str:
        name = "hello"
        if "add" in prompt:
            name = "add"
        return f"```python\ndef {name}(a, b):\n    return a + b\n```\n"

    def chat(self, request: ChatRequest) -> ChatResult:
        self.last = request
        prompt = _last_user_text(request.messages)
        content = self._code(prompt)
        return ChatResult(
            content=content,
            reasoning_content="Plan the function signature and body.",
            finish_reason="stop",
            usage=_usage(prompt, content),
        )

    def chat_stream(self, request: ChatRequest):
        self.last = request
        prompt = _last_user_text(request.messages)
        content = self._code(prompt)
        yield ChatChunk(reasoning_delta="Plan the function. ")
        for line in content.splitlines(keepends=True):
            yield ChatChunk(content_delta=line)
        yield ChatChunk(finish_reason="stop", usage=_usage(prompt, content))


class ASREngine:
    model_id = "asr-fixture"

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None = None) -> None:
        pass

    def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        chinese = "zh" in (request.filename or "").lower() or request.language == "zh"
        if chinese:
            text = "你好，这是一个语音测试。"
            segments = [
                {"id": 0, "start": 0.0, "end": 1.2, "text": "你好，"},
                {"id": 1, "start": 1.2, "end": 2.4, "text": "这是一个语音测试。"},
            ]
        else:
            text = "Hello, this is a speech test."
            segments = [
                {"id": 0, "start": 0.0, "end": 1.2, "text": "Hello, this is"},
                {"id": 1, "start": 1.2, "end": 2.4, "text": "a speech test."},
            ]
        return AudioTranscriptionResult(
            text=text,
            language="zh" if chinese else "en",
            duration=2.4,
            segments=segments,
            words=[
                {"word": "Hello,", "start": 0.0, "end": 0.3},
                {"word": "speech", "start": 1.6, "end": 1.9},
            ],
            usage={"total_tokens": max(1, len(text.split()))},
        )


class TTSEngine:
    model_id = "tts-fixture"

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None = None) -> None:
        pass

    def speech(self, request: SpeechRequest) -> SpeechResult:
        fmt = request.response_format or "mp3"
        if fmt == "wav":
            audio = _wav_bytes(request.input)
        else:
            audio = AUDIO_MAGIC.get(fmt, b"ID3") + b"\x00" * 32
        return SpeechResult(
            audio=audio,
            media_type=AUDIO_MEDIA.get(fmt, "audio/mpeg"),
        )


class AudioEngine(ASREngine, TTSEngine):
    model_id = "audio-fixture"


class ImageEngine:
    model_id = "image-fixture"

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None = None) -> None:
        pass

    def generate_images(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        count = max(1, request.n)
        return ImageGenerationResult(
            images=[PNG_1X1 for _ in range(count)],
            response_format=request.response_format,
            revised_prompt=f"{request.mode}: {request.prompt}",
        )


class VideoEngine:
    model_id = "video-fixture"

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.polls: dict[str, int] = {}
        self.seq = 0

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None = None) -> None:
        pass

    def create_video(self, request: VideoRequest) -> dict[str, Any]:
        self.seq += 1
        video_id = f"video_{self.seq}"
        job = {
            "id": video_id,
            "status": "queued",
            "progress": 0.0,
            "created_at": int(time.time()),
            "model": request.model,
            "prompt": request.prompt,
        }
        self.jobs[video_id] = job
        self.polls[video_id] = 0
        return dict(job)

    def list_videos(self) -> list[dict[str, Any]]:
        return [dict(job) for job in self.jobs.values()]

    def get_video(self, video_id: str) -> dict[str, Any]:
        if video_id not in self.jobs:
            raise KeyError(video_id)
        self.polls[video_id] += 1
        job = self.jobs[video_id]
        if self.polls[video_id] == 1:
            job["status"] = "in_progress"
            job["progress"] = 0.5
        elif self.polls[video_id] >= 2:
            job["status"] = "completed"
            job["progress"] = 1.0
            job["completed_at"] = int(time.time())
        return dict(job)

    def download_video(self, video_id: str) -> bytes:
        if video_id not in self.jobs:
            raise KeyError(video_id)
        return VIDEO_MP4

    def delete_video(self, video_id: str) -> bool:
        self.polls.pop(video_id, None)
        return self.jobs.pop(video_id, None) is not None
