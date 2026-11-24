"""Request validation and media-type behavior for host-owned routes."""

from __future__ import annotations

import pytest

from flashcli_bundle.protocol import (
    AudioTranscriptionResult,
    ChatResult,
    EmbeddingResult,
    ImageGenerationResult,
    SpeechResult,
)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from flashcli_bundle.infer.serve.app import build_app  # noqa: E402


class _Engine:
    model_id = "m"

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request):  # noqa: ANN001, ANN201
        return ChatResult(content="ok", finish_reason="stop")

    def chat_stream(self, request):  # noqa: ANN001, ANN201
        yield None

    def embed(self, request):  # noqa: ANN001, ANN201
        return EmbeddingResult(embeddings=[[0.0] for _ in request.input])

    def transcribe(self, request):  # noqa: ANN001, ANN201
        return AudioTranscriptionResult(text="ok")

    def speech(self, request):  # noqa: ANN001, ANN201
        return SpeechResult(audio=b"RIFF")

    def generate_images(self, request):  # noqa: ANN001, ANN201
        return ImageGenerationResult(images=[b"png"])

    def create_video(self, request):  # noqa: ANN001, ANN201
        return {"id": "video-1"}


_CAPS = [
    "openai.chat",
    "openai.completions",
    "openai.embeddings",
    "openai.audio.transcriptions",
    "openai.audio.speech",
    "openai.images.generations",
    "openai.videos",
]


def _client() -> TestClient:
    return TestClient(build_app(_Engine(), serve_capabilities=_CAPS))


def test_embeddings_dimensions_validation() -> None:
    with _client() as client:
        response = client.post(
            "/v1/embeddings", json={"input": "x", "dimensions": "nope"}
        )
        assert response.status_code == 400


def test_audio_numeric_validation() -> None:
    with _client() as client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("a.wav", b"RIFF", "audio/wav")},
            data={"temperature": "hot"},
        )
        assert response.status_code == 400
        response = client.post(
            "/v1/audio/speech", json={"input": "x", "speed": "fast"}
        )
        assert response.status_code == 400


def test_speech_media_type_follows_response_format() -> None:
    with _client() as client:
        response = client.post(
            "/v1/audio/speech", json={"input": "x", "response_format": "wav"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")


def test_images_and_videos_numeric_validation() -> None:
    with _client() as client:
        response = client.post(
            "/v1/images/generations", json={"prompt": "x", "n": "many"}
        )
        assert response.status_code == 400
        response = client.post("/v1/videos", json={"prompt": "x", "seconds": "long"})
        assert response.status_code == 400


def test_image_data_url_uses_result_media_type() -> None:
    class ImageEngine(_Engine):
        def generate_images(self, request):  # noqa: ANN001, ANN201
            return ImageGenerationResult(images=[b"jpeg"], media_type="image/jpeg")

    with TestClient(
        build_app(ImageEngine(), serve_capabilities=["openai.images.generations"])
    ) as client:
        response = client.post("/v1/images/generations", json={"prompt": "x"})
        assert response.status_code == 200
        assert response.json()["data"][0]["url"].startswith("data:image/jpeg;base64,")


def test_completions_boolean_stream_and_numeric_validation() -> None:
    with _client() as client:
        response = client.post(
            "/v1/completions", json={"prompt": "x", "stream": "false"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        response = client.post(
            "/v1/completions", json={"prompt": "x", "max_tokens": "many"}
        )
        assert response.status_code == 400
