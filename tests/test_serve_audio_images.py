"""OpenAI audio/image host protocol tests."""

from __future__ import annotations

import base64

import pytest

from flashcli_bundle.protocol import (
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    ImageGenerationRequest,
    ImageGenerationResult,
    SpeechRequest,
    SpeechResult,
)


class _Engine:
    model_id = "fake"

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request):  # noqa: ANN001
        raise NotImplementedError

    def chat_stream(self, request):  # noqa: ANN001
        yield  # pragma: no cover

    def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        assert request.file == b"audio-bytes"
        return AudioTranscriptionResult(
            text=f"{request.task}:hello",
            language="en",
            duration=1.5,
            segments=[{"id": 0, "start": 0.0, "end": 1.5, "text": "hello"}],
            words=[],
            usage={"total_tokens": 1},
        )

    def speech(self, request: SpeechRequest) -> SpeechResult:
        assert request.input == "hi"
        return SpeechResult(audio=b"RIFF....", media_type="audio/wav")

    def generate_images(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        assert request.prompt == "cat"
        return ImageGenerationResult(images=[b"png-bytes"], response_format=request.response_format)


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def test_transcription_and_translation() -> None:
    with _client(["openai.audio.transcriptions", "openai.audio.translations"]) as client:
        files = {"file": ("a.wav", b"audio-bytes", "audio/wav")}
        data = {"model": "fake", "language": "en", "response_format": "json"}
        response = client.post("/v1/audio/transcriptions", files=files, data=data)
        assert response.status_code == 200
        assert response.json() == {"text": "transcribe:hello"}

        response = client.post("/v1/audio/translations", files=files, data=data)
        assert response.status_code == 200
        assert response.json() == {"text": "translate:hello"}


def test_transcription_verbose_json() -> None:
    with _client(["openai.audio.transcriptions"]) as client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", b"audio-bytes", "audio/wav")},
            data={"response_format": "verbose_json"},
        )
        body = response.json()
        assert body["language"] == "en"
        assert body["segments"][0]["text"] == "hello"


def test_speech() -> None:
    with _client(["openai.audio.speech"]) as client:
        response = client.post(
            "/v1/audio/speech",
            json={"model": "fake", "voice": "alloy", "input": "hi", "response_format": "wav"},
        )
        assert response.status_code == 200
        assert response.content == b"RIFF...."
        assert response.headers["content-type"].startswith("audio/wav")


def test_image_generation_url_and_b64() -> None:
    with _client(["openai.images.generations"]) as client:
        response = client.post(
            "/v1/images/generations",
            json={"model": "fake", "prompt": "cat", "response_format": "url"},
        )
        body = response.json()
        assert body["data"][0]["url"].startswith("data:image/png;base64,")

        response = client.post(
            "/v1/images/generations",
            json={"model": "fake", "prompt": "cat", "response_format": "b64_json"},
        )
        encoded = response.json()["data"][0]["b64_json"]
        assert base64.b64decode(encoded) == b"png-bytes"


def test_image_edit_multipart() -> None:
    with _client(["openai.images.edits"]) as client:
        response = client.post(
            "/v1/images/edits",
            files={"image": ("in.png", b"input", "image/png")},
            data={"prompt": "cat", "response_format": "b64_json"},
        )
        assert response.status_code == 200
        assert response.json()["data"][0]["b64_json"]


def test_audio_image_501_without_engine_methods() -> None:
    class Empty(_Engine):
        transcribe = None
        speech = None
        generate_images = None

    with _client(
        ["openai.audio.transcriptions", "openai.audio.speech", "openai.images.generations"],
        engine=Empty(),
    ) as client:
        assert client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", b"x", "audio/wav")},
        ).status_code == 501
        assert client.post(
            "/v1/audio/speech", json={"input": "hi"}
        ).status_code == 501
        assert client.post(
            "/v1/images/generations", json={"prompt": "cat"}
        ).status_code == 501


def test_audio_image_routes_are_gated() -> None:
    with _client([]) as client:
        assert client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", b"x", "audio/wav")},
        ).status_code == 404
        assert client.post(
            "/v1/images/generations", json={"prompt": "cat"}
        ).status_code == 404
