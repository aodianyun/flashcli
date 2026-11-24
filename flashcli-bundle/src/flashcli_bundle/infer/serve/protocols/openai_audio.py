"""OpenAI audio transcription/translation/speech host routes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from flashcli_bundle.capabilities import (
    OPENAI_AUDIO_TRANSCRIPTIONS,
    OPENAI_AUDIO_TRANSLATIONS,
)
from flashcli_bundle.infer.engines.base import (
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    SpeechRequest,
    SpeechResult,
)
from flashcli_bundle.infer.serve.inference import InferenceGate
from flashcli_bundle.infer.serve.protocols.common import call_engine, new_id

_AUDIO_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


def _str(form: Any, key: str, default: str | None = None) -> str | None:
    value = form.get(key)
    if value is None or value == "":
        return default
    return str(value)


def _float(form: Any, key: str) -> float | None:
    value = _str(form, key)
    return float(value) if value is not None else None


async def _transcription_request(form: Any, task: str) -> AudioTranscriptionRequest:
    upload = form.get("file")
    if upload is None:
        raise HTTPException(400, "file is required")
    data = await upload.read()
    if not data:
        raise HTTPException(400, "file is empty")
    granularities = form.getlist("timestamp_granularities[]") or form.getlist("timestamp_granularities")
    return AudioTranscriptionRequest(
        task=task,
        file=data,
        filename=getattr(upload, "filename", None) or "audio",
        model=_str(form, "model", "") or "",
        language=_str(form, "language"),
        prompt=_str(form, "prompt"),
        response_format=_str(form, "response_format", "json") or "json",
        temperature=_float(form, "temperature"),
        timestamp_granularities=[str(g) for g in granularities] or None,
        extras={
            k: str(v)
            for k, v in form.items()
            if k
            not in {
                "file", "model", "language", "prompt", "response_format",
                "temperature", "timestamp_granularities[]", "timestamp_granularities",
            }
            and not hasattr(v, "read")
        },
    )


def _srt(segments: list[dict[str, Any]]) -> str:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines: list[str] = []
    for index, item in enumerate(segments, 1):
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        lines.extend([str(index), f"{stamp(start)} --> {stamp(end)}", str(item.get("text", "")), ""])
    return "\n".join(lines)


def _vtt(segments: list[dict[str, Any]]) -> str:
    out = ["WEBVTT", ""]
    for item in segments:
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))

        def stamp(seconds: float) -> str:
            ms = int(round(seconds * 1000))
            h, ms = divmod(ms, 3_600_000)
            m, ms = divmod(ms, 60_000)
            s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

        out.extend([f"{stamp(start)} --> {stamp(end)}", str(item.get("text", "")), ""])
    return "\n".join(out)


def _transcription_response(
    result: AudioTranscriptionResult,
    response_format: str,
    *,
    task: str = "transcribe",
) -> Any:
    if response_format == "text":
        return PlainTextResponse(result.text)
    if response_format == "srt":
        return PlainTextResponse(_srt(result.segments) or result.text)
    if response_format == "vtt":
        return PlainTextResponse(_vtt(result.segments) or result.text)
    if response_format == "verbose_json":
        return {
            "task": task,
            "language": result.language,
            "duration": result.duration,
            "text": result.text,
            "segments": result.segments,
            "words": result.words,
        }
    return {"text": result.text}


def mount_transcriptions(
    app: FastAPI,
    engine: Any,
    gate: InferenceGate,
    capabilities: set[str],
) -> None:
    async def handle(request: Request, task: str):
        method = getattr(engine, "transcribe", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose transcription", "type": "not_implemented"}},
            )
        form = await request.form()
        req = await _transcription_request(form, task)
        request_id = request.headers.get("x-request-id") or new_id("asr")
        try:
            result = await call_engine(gate, engine, request_id, method, req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"transcription failed: {exc}") from exc
        if not isinstance(result, AudioTranscriptionResult):
            raise HTTPException(500, "engine transcribe() must return AudioTranscriptionResult")
        return _transcription_response(result, req.response_format, task=task)

    if OPENAI_AUDIO_TRANSCRIPTIONS in capabilities:
        @app.post("/v1/audio/transcriptions")
        async def transcriptions(request: Request):
            return await handle(request, "transcribe")

    if OPENAI_AUDIO_TRANSLATIONS in capabilities:
        @app.post("/v1/audio/translations")
        async def translations(request: Request):
            return await handle(request, "translate")


def mount_speech(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.post("/v1/audio/speech")
    async def speech(request: Request, body: dict[str, Any]):
        text = body.get("input")
        if not isinstance(text, str) or not text:
            raise HTTPException(400, "input is required")
        method = getattr(engine, "speech", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose speech", "type": "not_implemented"}},
            )
        req = SpeechRequest(
            input=text,
            model=str(body.get("model", "")),
            voice=str(body.get("voice", "alloy")),
            response_format=str(body.get("response_format", "mp3") or "mp3"),
            speed=float(body.get("speed", 1.0) or 1.0),
            instructions=body.get("instructions"),
            extras={k: v for k, v in body.items() if k not in {"input", "model", "voice", "response_format", "speed", "instructions"}},
        )
        request_id = request.headers.get("x-request-id") or new_id("tts")
        try:
            result = await call_engine(gate, engine, request_id, method, req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"speech failed: {exc}") from exc
        if not isinstance(result, SpeechResult):
            raise HTTPException(500, "engine speech() must return SpeechResult")
        media_type = result.media_type or _AUDIO_TYPES.get(req.response_format, "audio/mpeg")
        return Response(content=result.audio, media_type=media_type)
