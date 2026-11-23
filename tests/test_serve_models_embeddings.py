"""Anthropic model metadata and OpenAI embeddings tests."""

from __future__ import annotations

import base64
import struct

import pytest

from flashcli_bundle.protocol import EmbeddingRequest, EmbeddingResult


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

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[0.1, 0.2] for _ in request.input],
            usage={"prompt_tokens": len(request.input), "total_tokens": len(request.input)},
        )


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def test_anthropic_model_list_and_retrieve() -> None:
    with _client(["anthropic.models"]) as client:
        listing = client.get("/v1/models", headers={"anthropic-version": "2023-06-01"})
        assert listing.status_code == 200
        assert listing.json()["data"][0]["type"] == "model"
        assert listing.json()["data"][0]["id"] == "fake"
        assert client.get("/v1/models/fake").json()["id"] == "fake"
        assert client.get("/v1/models/missing").status_code == 404
        # Without the Anthropic header the OpenAI shape remains.
        assert client.get("/v1/models").json()["object"] == "list"


def test_embeddings_float_and_base64() -> None:
    with _client(["openai.embeddings"]) as client:
        response = client.post("/v1/embeddings", json={"model": "fake", "input": ["a", "b"]})
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "list"
        assert body["data"][0]["embedding"] == [0.1, 0.2]
        assert body["usage"]["prompt_tokens"] == 2

        encoded = client.post(
            "/v1/embeddings",
            json={"model": "fake", "input": "a", "encoding_format": "base64"},
        ).json()["data"][0]["embedding"]
        raw = base64.b64decode(encoded)
        assert struct.unpack("<2f", raw) == pytest.approx((0.1, 0.2))


def test_embeddings_without_engine_method_returns_501() -> None:
    class NoEmbed(_Engine):
        embed = None

    with _client(["openai.embeddings"], engine=NoEmbed()) as client:
        response = client.post("/v1/embeddings", json={"input": "a"})
        assert response.status_code == 501


def test_models_always_available_and_embeddings_gated() -> None:
    with _client([]) as client:
        assert client.get("/v1/models/fake").json()["object"] == "model"
        assert client.get("/v1/models/missing").status_code == 404
        assert client.post("/v1/embeddings", json={"input": "a"}).status_code == 404
