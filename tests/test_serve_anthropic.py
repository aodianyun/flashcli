"""Anthropic Messages host protocol tests."""

from __future__ import annotations

import json

import pytest

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult


class _Engine:
    model_id = "fake"

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request: ChatRequest) -> ChatResult:
        assert request.messages[0].role == "system"
        assert request.tools
        return ChatResult(
            content="hello",
            reasoning_content="thinking",
            finish_reason="tool_calls",
            usage={"prompt_tokens": 3, "completion_tokens": 4},
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                }
            ],
        )

    def chat_stream(self, request: ChatRequest):
        del request
        yield ChatChunk(reasoning_delta="think")
        yield ChatChunk(content_delta="hello")
        yield ChatChunk(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                }
            ],
            usage={"prompt_tokens": 3, "completion_tokens": 4},
            finish_reason="tool_calls",
        )

    def count_tokens(self, request: ChatRequest) -> int:
        del request
        return 42


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def _body(stream: bool = False) -> dict:
    return {
        "model": "fake",
        "max_tokens": 64,
        "system": "be concise",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ],
        "tools": [
            {
                "name": "lookup",
                "description": "lookup",
                "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            }
        ],
        "thinking": {"type": "enabled", "budget_tokens": 32},
        "stream": stream,
    }


def test_messages_non_stream_maps_blocks_and_tools() -> None:
    with _client(["anthropic.messages"]) as client:
        response = client.post("/v1/messages", json=_body())
        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "message"
        assert body["stop_reason"] == "tool_use"
        assert body["usage"] == {"input_tokens": 3, "output_tokens": 4}
        assert [b["type"] for b in body["content"]] == ["thinking", "text", "tool_use"]
        assert body["content"][2]["input"] == {"q": "x"}


def test_messages_stream_emits_expected_events() -> None:
    with _client(["anthropic.messages"]) as client:
        response = client.post("/v1/messages", json=_body(stream=True))
        assert response.status_code == 200
        events = [
            line.removeprefix("event: ")
            for line in response.text.splitlines()
            if line.startswith("event: ")
        ]
        assert "message_start" in events
        assert "content_block_start" in events
        assert "content_block_delta" in events
        assert "message_delta" in events
        assert "message_stop" in events


def test_count_tokens() -> None:
    with _client(["anthropic.count_tokens"]) as client:
        response = client.post("/v1/messages/count_tokens", json=_body())
        assert response.status_code == 200
        assert response.json() == {"input_tokens": 42}


def test_count_tokens_without_engine_method_returns_501() -> None:
    class NoCounter(_Engine):
        count_tokens = None

    with _client(["anthropic.count_tokens"], engine=NoCounter()) as client:
        response = client.post("/v1/messages/count_tokens", json=_body())
        assert response.status_code == 501


def test_anthropic_routes_are_gated() -> None:
    with _client([]) as client:
        assert client.post("/v1/messages", json=_body()).status_code == 404
        assert client.post("/v1/messages/count_tokens", json=_body()).status_code == 404
