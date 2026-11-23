"""OpenAI Responses host protocol tests."""

from __future__ import annotations

import time

import pytest

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult


class _Engine:
    model_id = "fake"

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request: ChatRequest) -> ChatResult:
        self.requests.append(request)
        return ChatResult(
            content="hello",
            reasoning_content="thinking",
            finish_reason="stop",
            usage={"prompt_tokens": 2, "completion_tokens": 3},
        )

    def chat_stream(self, request: ChatRequest):
        self.requests.append(request)
        yield ChatChunk(reasoning_delta="think")
        yield ChatChunk(content_delta="hello")
        yield ChatChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 2, "completion_tokens": 3},
        )


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def _body(stream: bool = False) -> dict:
    return {
        "model": "fake",
        "instructions": "be concise",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        ],
        "max_output_tokens": 64,
        "stream": stream,
    }


def test_responses_non_stream() -> None:
    engine = _Engine()
    with _client(["openai.responses"], engine) as client:
        response = client.post("/v1/responses", json=_body())
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert body["output_text"] == "hello"
        assert body["usage"]["input_tokens"] == 2
        assert {item["type"] for item in body["output"]} == {"reasoning", "message"}
        assert engine.requests[0].messages[0].role == "system"


def test_responses_stream_events() -> None:
    with _client(["openai.responses"]) as client:
        response = client.post("/v1/responses", json=_body(stream=True))
        assert response.status_code == 200
        events = [
            line.removeprefix("event: ")
            for line in response.text.splitlines()
            if line.startswith("event: ")
        ]
        for event in (
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.output_text.delta",
            "response.completed",
        ):
            assert event in events


def test_responses_previous_response_id() -> None:
    engine = _Engine()
    with _client(["openai.responses"], engine) as client:
        first = client.post("/v1/responses", json=_body()).json()
        second = client.post(
            "/v1/responses",
            json={
                "model": "fake",
                "input": "again",
                "previous_response_id": first["id"],
            },
        )
        assert second.status_code == 200
        assert len(engine.requests) == 2
        # Previous system + user + assistant, then the new user turn.
        roles = [m.role for m in engine.requests[1].messages]
        assert roles == ["system", "user", "assistant", "user"]


def test_responses_tools_mapping() -> None:
    engine = _Engine()
    with _client(["openai.responses"], engine) as client:
        response = client.post(
            "/v1/responses",
            json={
                "model": "fake",
                "input": "hi",
                "tools": [
                    {"type": "function", "name": "lookup", "parameters": {"type": "object"}}
                ],
                "tool_choice": {"type": "function", "name": "lookup"},
            },
        )
        assert response.status_code == 200
        assert engine.requests[0].tools[0]["function"]["name"] == "lookup"


def test_responses_background_lifecycle() -> None:
    with _client(["openai.responses"]) as client:
        response = client.post("/v1/responses", json={**_body(), "background": True})
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"
        response_id = response.json()["id"]

        current = response.json()
        for _ in range(100):
            current = client.get(f"/v1/responses/{response_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current["status"] == "completed"
        assert current["output_text"] == "hello"
        assert client.post(f"/v1/responses/{response_id}/cancel").status_code == 400
        assert client.delete(f"/v1/responses/{response_id}").json()["deleted"] is True
        assert client.get(f"/v1/responses/{response_id}").status_code == 404


def test_responses_retrieve_and_delete_stored_response() -> None:
    with _client(["openai.responses"]) as client:
        created = client.post("/v1/responses", json=_body()).json()
        fetched = client.get(f"/v1/responses/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["output_text"] == "hello"
        assert client.post(f"/v1/responses/{created['id']}/cancel").status_code == 400
        assert client.delete(f"/v1/responses/{created['id']}").json()["deleted"] is True
        assert client.get(f"/v1/responses/{created['id']}").status_code == 404


def test_responses_is_gated() -> None:
    with _client([]) as client:
        assert client.post("/v1/responses", json=_body()).status_code == 404
