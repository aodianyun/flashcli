"""OpenAI Realtime WebSocket transport tests."""

from __future__ import annotations

import json

import pytest


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

    async def realtime_session(self, websocket, model) -> None:  # noqa: ANN001
        assert model == "fake"
        await websocket.send_text(json.dumps({"type": "session.created", "model": model}))
        await websocket.close()


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def test_realtime_transport_delegates_to_engine() -> None:
    with _client(["openai.realtime"]) as client:
        with client.websocket_connect("/v1/realtime?model=fake") as ws:
            assert ws.receive_json() == {"type": "session.created", "model": "fake"}


def test_realtime_without_engine_handler_reports_error() -> None:
    class Empty(_Engine):
        realtime_session = None

    with _client(["openai.realtime"], engine=Empty()) as client:
        with client.websocket_connect("/v1/realtime?model=fake") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert message["error"]["type"] == "not_implemented"


def test_realtime_route_is_gated() -> None:
    from starlette.websockets import WebSocketDisconnect

    with _client([]) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime") as ws:
                ws.receive_json()
