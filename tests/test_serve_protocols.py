"""Host-owned protocol route tests (FastAPI optional)."""

from __future__ import annotations

import pytest

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult


class _Engine:
    model_id = "fake"

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request: ChatRequest) -> ChatResult:
        del request
        return ChatResult(content="hello", finish_reason="stop", usage={"total_tokens": 2})

    def chat_stream(self, request: ChatRequest):
        del request
        yield ChatChunk(content_delta="he")
        yield ChatChunk(content_delta="llo", finish_reason="stop")


def _app(caps):
    pytest.importorskip("fastapi")
    from flashcli_bundle.infer.serve.app import build_app

    return build_app(_Engine(), serve_capabilities=caps)


def _client(caps):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(_app(caps))


def test_route_registry_mounts_completions_and_planned_501() -> None:
    pytest.importorskip("fastapi")
    paths = {r.path for r in _app(
        ["openai.chat", "openai.completions", "openai.responses", "anthropic.messages"]
    ).routes if hasattr(r, "path")}
    assert "/v1/chat/completions" in paths
    assert "/v1/completions" in paths
    assert "/v1/responses" in paths
    assert "/v1/messages" in paths


def test_openai_completions_non_stream() -> None:
    with _client(["openai.completions"]) as client:
        response = client.post("/v1/completions", json={"model": "fake", "prompt": "hi"})
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"] == "hello"


def test_openai_completions_stream() -> None:
    with _client(["openai.completions"]) as client:
        response = client.post(
            "/v1/completions",
            json={"model": "fake", "prompt": "hi", "stream": True},
        )
        assert response.status_code == 200
        assert '"text": "he"' in response.text
        assert "[DONE]" in response.text


def test_planned_capability_returns_501() -> None:
    with _client(["openai.embeddings"]) as client:
        response = client.post("/v1/embeddings", json={})
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "capability_not_implemented"


def test_disabled_capability_is_not_mounted() -> None:
    with _client([]) as client:
        assert client.post("/v1/completions", json={"prompt": "hi"}).status_code == 404
