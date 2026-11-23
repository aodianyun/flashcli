"""OpenAI Realtime WebSocket transport tests."""

from __future__ import annotations

import base64
import json

import pytest

from flashcli_bundle.protocol import AudioTranscriptionResult, ChatChunk, ChatResult


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


def test_realtime_host_state_machine_text_response() -> None:
    class TextEngine(_Engine):
        realtime_session = None

        def chat(self, request):  # noqa: ANN001
            return ChatResult(content="hello", finish_reason="stop", usage={})

        def chat_stream(self, request):  # noqa: ANN001
            yield ChatChunk(content_delta="he")
            yield ChatChunk(content_delta="llo", finish_reason="stop")

    with _client(["openai.realtime"], engine=TextEngine()) as client:
        with client.websocket_connect("/v1/realtime?model=fake") as ws:
            created = ws.receive_json()
            assert created["type"] == "session.created"
            assert created["session"]["model"] == "fake"

            ws.send_json(
                {
                    "type": "session.update",
                    "session": {"instructions": "be brief", "tools": []},
                }
            )
            updated = ws.receive_json()
            assert updated["type"] == "session.updated"
            assert updated["session"]["instructions"] == "be brief"

            ws.send_json(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    },
                }
            )
            item = ws.receive_json()
            assert item["type"] == "conversation.item.created"
            item_id = item["item"]["id"]

            ws.send_json({"type": "conversation.item.delete", "item_id": item_id})
            assert ws.receive_json()["type"] == "conversation.item.deleted"

            ws.send_json(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    },
                }
            )
            assert ws.receive_json()["type"] == "conversation.item.created"

            ws.send_json({"type": "response.create"})
            events: list[str] = []
            while True:
                event = ws.receive_json()
                events.append(event["type"])
                if event["type"] == "response.done":
                    done = event
                    break
            assert "response.created" in events
            assert "response.output_text.delta" in events
            assert done["response"]["status"] == "completed"
            assert done["response"]["output"][0]["content"][0]["text"] == "hello"

            ws.send_json({"type": "response.cancel"})
            assert ws.receive_json()["type"] == "error"

            ws.send_json({"type": "input_audio_buffer.clear"})
            assert ws.receive_json()["type"] == "input_audio_buffer.cleared"

            ws.send_json({"type": "bogus.event"})
            error = ws.receive_json()
            assert error["type"] == "error"


def test_realtime_audio_buffer_transcription_and_items() -> None:
    class AudioEngine(_Engine):
        realtime_session = None

        def __init__(self) -> None:
            self.requests = []

        def transcribe(self, request):  # noqa: ANN001
            assert request.file == b"abc"
            return AudioTranscriptionResult(text="audio text")

        def chat_stream(self, request):  # noqa: ANN001
            self.requests.append(request)
            yield ChatChunk(content_delta="hello", finish_reason="stop")

    engine = AudioEngine()
    with _client(["openai.realtime"], engine=engine) as client:
        with client.websocket_connect("/v1/realtime?model=fake") as ws:
            ws.receive_json()
            ws.send_json(
                {
                    "type": "session.update",
                    "session": {
                        "id": "hacked",
                        "model": "hacked",
                        "instructions": "be brief",
                        "unknown": 1,
                    },
                }
            )
            updated = ws.receive_json()["session"]
            assert updated["id"] != "hacked"
            assert updated["model"] == "fake"
            assert updated["instructions"] == "be brief"
            assert "unknown" not in updated

            ws.send_json(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(b"abc").decode(),
                }
            )
            ws.send_json({"type": "input_audio_buffer.commit"})
            assert ws.receive_json()["type"] == "input_audio_buffer.committed"
            item = ws.receive_json()
            assert item["item"]["content"][0]["transcript"] == "audio text"

            ws.send_json(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": "http://x/y.png"},
                            {"type": "input_text", "text": "look"},
                        ],
                    },
                }
            )
            assert ws.receive_json()["type"] == "conversation.item.created"

            ws.send_json(
                {
                    "type": "conversation.item.truncate",
                    "item_id": "x",
                    "content_index": 0,
                    "audio_end_ms": 10,
                }
            )
            assert ws.receive_json()["type"] == "conversation.item.truncated"
            ws.send_json({"type": "conversation.item.delete", "item_id": "missing"})
            assert ws.receive_json()["type"] == "error"

            ws.send_json({"type": "response.create"})
            while True:
                event = ws.receive_json()
                if event["type"] == "response.done":
                    break
            last = engine.requests[-1].messages[-1]
            assert isinstance(last.content, list)
            assert any(part.get("type") == "image_url" for part in last.content)

            ws.send_json({"type": "input_audio_buffer.clear"})
            assert ws.receive_json()["type"] == "input_audio_buffer.cleared"
            ws.send_json({"type": "input_audio_buffer.commit"})
            assert ws.receive_json()["type"] == "error"


def test_realtime_tool_call_response() -> None:
    class ToolEngine(_Engine):
        realtime_session = None

        def chat_stream(self, request):  # noqa: ANN001
            yield ChatChunk(
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                    }
                ],
                finish_reason="tool_calls",
            )

    with _client(["openai.realtime"], engine=ToolEngine()) as client:
        with client.websocket_connect("/v1/realtime?model=fake") as ws:
            ws.receive_json()
            ws.send_json({"type": "response.create"})
            events: list[str] = []
            while True:
                event = ws.receive_json()
                events.append(event["type"])
                if event["type"] == "response.done":
                    done = event
                    break
            assert "response.function_call_arguments.done" in events
            output = done["response"]["output"]
            assert output[0]["type"] == "function_call"
            assert output[0]["name"] == "lookup"


def test_realtime_route_is_gated() -> None:
    from starlette.websockets import WebSocketDisconnect

    with _client([]) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/realtime") as ws:
                ws.receive_json()
