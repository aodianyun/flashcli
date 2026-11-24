"""Exhaustive host-owned OpenAI/Anthropic protocol matrix (real request/response)."""

from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from flashcli_bundle.capabilities import (  # noqa: E402
    effective_serve_capabilities,
    parse_serve_capabilities,
    validate_serve_capabilities,
)
from flashcli_bundle.infer.serve.app import build_app  # noqa: E402
from flashcli_bundle.infer.serve.inference import (  # noqa: E402
    GpuBusyError,
    InferenceGate,
    iter_on_inference_loop,
)
from flashcli_bundle.manifest import EntrySpec  # noqa: E402
from flashcli_bundle.protocol import (  # noqa: E402
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

ALL_CAPS = [
    "openai.chat",
    "openai.completions",
    "openai.responses",
    "openai.embeddings",
    "openai.moderations",
    "openai.audio.transcriptions",
    "openai.audio.translations",
    "openai.audio.speech",
    "openai.images.generations",
    "openai.images.edits",
    "openai.images.variations",
    "openai.videos",
    "openai.realtime",
    "anthropic.messages",
    "anthropic.count_tokens",
    "anthropic.models",
]

TOOL_CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "lookup", "arguments": '{"q": "x"}'},
}


class FullEngine:
    model_id = "fake-model"

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
            finish_reason="tool_calls",
            usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            tool_calls=[TOOL_CALL],
        )

    def chat_stream(self, request: ChatRequest):
        self.requests.append(request)
        yield ChatChunk(reasoning_delta="think ")
        yield ChatChunk(content_delta="hello")
        yield ChatChunk(
            tool_calls=[TOOL_CALL],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 3, "completion_tokens": 4},
        )

    def count_tokens(self, request: ChatRequest) -> int:
        del request
        return 42

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[[0.1, 0.2] for _ in request.input],
            usage={"prompt_tokens": len(request.input), "total_tokens": len(request.input)},
        )

    def moderate(self, request: ModerationRequest) -> ModerationResult:
        return ModerationResult(
            results=[
                {"flagged": "bad" in text, "categories": {}, "category_scores": {}}
                for text in request.input
            ],
            usage={"total_tokens": len(request.input)},
        )

    def transcribe(self, request: AudioTranscriptionRequest) -> AudioTranscriptionResult:
        return AudioTranscriptionResult(
            text=f"{request.task}:hello",
            language="en",
            duration=1.5,
            segments=[{"id": 0, "start": 0.0, "end": 1.5, "text": "hello"}],
            words=[{"word": "hello", "start": 0.0, "end": 1.5}],
            usage={"total_tokens": 1},
        )

    def speech(self, request: SpeechRequest) -> SpeechResult:
        return SpeechResult(audio=b"RIFF", media_type="audio/wav")

    def generate_images(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return ImageGenerationResult(
            images=[b"PNG"], response_format=request.response_format, revised_prompt="rev"
        )

    def create_video(self, request: VideoRequest) -> dict:
        return {"id": "video_1", "status": "queued", "model": request.model}

    def get_video(self, video_id: str) -> dict:
        if video_id != "video_1":
            raise KeyError(video_id)
        return {"id": video_id, "status": "completed"}

    def download_video(self, video_id: str) -> bytes:
        return b"mp4"

    def delete_video(self, video_id: str) -> bool:
        return video_id == "video_1"

    async def realtime_session(self, websocket, model) -> None:  # noqa: ANN001
        await websocket.send_text(json.dumps({"type": "session.created", "model": model}))
        await websocket.close()


def make_client(caps, engine=None) -> TestClient:
    return TestClient(build_app(engine or FullEngine(), serve_capabilities=caps))


# --------------------------------------------------------------------------- #
# health / models
# --------------------------------------------------------------------------- #


def test_health_openai_models_and_anthropic_models() -> None:
    with make_client(ALL_CAPS) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "model": "fake-model",
            "inference_busy": False,
        }

        openai_list = client.get("/v1/models").json()
        assert openai_list["object"] == "list"
        assert openai_list["data"][0]["owned_by"] == "flashcli"

        anthropic_list = client.get(
            "/v1/models", headers={"anthropic-version": "2023-06-01"}
        ).json()
        assert anthropic_list["data"][0]["type"] == "model"
        assert anthropic_list["first_id"] == "fake-model"
        assert anthropic_list["has_more"] is False

        anthropic_retrieved = client.get(
            "/v1/models/fake-model", headers={"anthropic-version": "2023-06-01"}
        )
        assert anthropic_retrieved.status_code == 200
        assert anthropic_retrieved.json()["type"] == "model"
        openai_retrieved = client.get("/v1/models/fake-model")
        assert openai_retrieved.json()["object"] == "model"
        assert client.get("/v1/models/nope").json()["error"]["code"] == "model_not_found"
        assert (
            client.get(
                "/v1/models/nope", headers={"anthropic-version": "2023-06-01"}
            ).json()["type"]
            == "error"
        )


# --------------------------------------------------------------------------- #
# OpenAI chat completions
# --------------------------------------------------------------------------- #


def test_chat_non_stream_full_mapping() -> None:
    engine = FullEngine()
    with make_client(["openai.chat"], engine) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "m",
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 12,
                "temperature": 0.2,
                "top_p": 0.9,
                "top_k": 5,
                "stop": "END",
                "seed": 7,
                "custom_field": "x",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["model"] == "fake-model"
        choice = body["choices"][0]
        assert choice["message"]["content"] == "hello"
        assert choice["message"]["reasoning_content"] == "thinking"
        assert choice["message"]["tool_calls"] == [TOOL_CALL]
        assert choice["finish_reason"] == "tool_calls"
        assert body["usage"]["total_tokens"] == 7

        sent = engine.requests[0]
        assert sent.max_tokens == 12
        assert sent.temperature == pytest.approx(0.2)
        assert sent.top_p == pytest.approx(0.9)
        assert sent.top_k == 5
        assert sent.stop == ["END"]
        assert sent.seed == 7
        assert sent.extras == {"custom_field": "x"}


def test_chat_stream_full_mapping() -> None:
    with make_client(["openai.chat"]) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"reasoning_content": "think "' in response.text
        assert '"content": "hello"' in response.text
        assert '"tool_calls"' in response.text
        assert '"finish_reason": "tool_calls"' in response.text
        assert '"usage"' in response.text
        assert response.text.rstrip().endswith("data: [DONE]")


def test_chat_invalid_and_engine_errors() -> None:
    with make_client(["openai.chat"]) as client:
        assert client.post("/v1/chat/completions", json={}).status_code == 400
        assert (
            client.post("/v1/chat/completions", json={"messages": []}).status_code == 400
        )

    class Boom(FullEngine):
        def chat(self, request):  # noqa: ANN001
            raise RuntimeError("boom")

    with make_client(["openai.chat"], Boom()) as client:
        response = client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]}
        )
        assert response.status_code == 500
        assert "inference failed" in response.text


def test_chat_gpu_busy_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def busy(self, request_id):  # noqa: ANN001
        raise GpuBusyError("busy")

    monkeypatch.setattr(InferenceGate, "acquire", busy)
    with make_client(["openai.chat"]) as client:
        response = client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]}
        )
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        streamed = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}], "stream": True},
        )
        assert streamed.status_code == 503


# --------------------------------------------------------------------------- #
# OpenAI legacy completions
# --------------------------------------------------------------------------- #


def test_completions_variants() -> None:
    with make_client(["openai.completions"]) as client:
        body = client.post(
            "/v1/completions", json={"prompt": "hi", "echo": True, "max_tokens": 4}
        ).json()
        assert body["object"] == "text_completion"
        assert body["choices"][0]["text"] == "hihello"

        array = client.post(
            "/v1/completions", json={"prompt": ["a", "b"]}
        ).json()
        assert len(array["choices"]) == 2

        for bad, code in (
            ({"prompt": []}, 400),
            ({"prompt": 3}, 400),
            ({"prompt": "x", "logprobs": 1}, 400),
            ({"prompt": "x", "n": -1}, 400),
            ({"prompt": "x", "n": 0}, 400),
            ({"prompt": "x", "n": "abc"}, 400),
            ({"prompt": ""}, 400),
        ):
            assert client.post("/v1/completions", json=bad).status_code == code

        multi = client.post(
            "/v1/completions", json={"prompt": ["a", "b"], "n": 2}
        ).json()
        assert [choice["index"] for choice in multi["choices"]] == [0, 1, 2, 3]

        streamed = client.post(
            "/v1/completions", json={"prompt": "hi", "stream": True}
        )
        assert streamed.status_code == 200
        assert '"text": "hello"' in streamed.text
        assert "[DONE]" in streamed.text

        streamed_multi = client.post(
            "/v1/completions", json={"prompt": "hi", "n": 2, "stream": True}
        )
        assert streamed_multi.status_code == 200
        assert '"index": 1' in streamed_multi.text
        assert "[DONE]" in streamed_multi.text


# --------------------------------------------------------------------------- #
# OpenAI responses
# --------------------------------------------------------------------------- #


def test_responses_output_items_and_stream() -> None:
    with make_client(["openai.responses"]) as client:
        body = client.post(
            "/v1/responses",
            json={
                "model": "m",
                "input": "hi",
                "instructions": "be brief",
                "max_output_tokens": 32,
                "metadata": {"k": "v"},
                "text": {"format": {"type": "json_object"}},
            },
        ).json()
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert body["output_text"] == "hello"
        assert body["metadata"] == {"k": "v"}
        kinds = [item["type"] for item in body["output"]]
        assert kinds == ["reasoning", "message", "function_call"]
        assert body["usage"]["total_tokens"] == 7

        streamed = client.post(
            "/v1/responses", json={"input": "hi", "stream": True}
        ).text
        for event in (
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.reasoning_summary_text.delta",
            "response.output_text.delta",
            "response.function_call_arguments.done",
            "response.completed",
        ):
            assert event in streamed


def test_responses_inputs_and_errors() -> None:
    engine = FullEngine()
    with make_client(["openai.responses"], engine) as client:
        client.post(
            "/v1/responses",
            json={
                "input": [
                    {"type": "message", "role": "user", "content": [
                        {"type": "input_text", "text": "hi"},
                        {"type": "input_image", "image_url": {"url": "http://x/y.png"}},
                    ]},
                    {"type": "function_call", "name": "f", "call_id": "c1", "arguments": "{}"},
                    {"type": "function_call_output", "call_id": "c1", "output": "ok"},
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "r"}]},
                ]
            },
        )
        roles = [m.role for m in engine.requests[-1].messages]
        assert roles == ["user", "assistant", "tool", "assistant"]

        encoded = base64.b64encode(b"file text").decode()
        file_response = client.post(
            "/v1/responses",
            json={
                "input": [{
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "input_file",
                        "file_data": encoded,
                        "filename": "a.txt",
                    }],
                }]
            },
        )
        assert file_response.status_code == 200
        assert "file text" in engine.requests[-1].messages[0].content
        assert client.post(
            "/v1/responses",
            json={"input": [{"type": "message", "content": [{"type": "input_file", "file_id": "f"}]}]},
        ).status_code == 501
        assert client.post(
            "/v1/responses",
            json={"input": "x", "background": True, "stream": True},
        ).status_code == 400

        background = client.post(
            "/v1/responses", json={"input": "x", "background": True}
        )
        assert background.status_code == 200
        assert background.json()["status"] == "in_progress"
        background_id = background.json()["id"]
        current = background.json()
        for _ in range(100):
            current = client.get(f"/v1/responses/{background_id}").json()
            if current["status"] not in ("in_progress", "queued"):
                break
            time.sleep(0.02)
        assert current["status"] == "completed"
        assert current["output_text"] == "hello"
        assert client.post(f"/v1/responses/{background_id}/cancel").status_code == 400
        assert client.delete(f"/v1/responses/{background_id}").json()["deleted"] is True
        assert client.get(f"/v1/responses/{background_id}").status_code == 404

        assert client.post(
            "/v1/responses",
            json={"input": "x", "tools": [{"type": "web_search"}]},
        ).status_code == 400
        assert client.post(
            "/v1/responses", json={"input": "x", "previous_response_id": "missing"}
        ).status_code == 400
        assert client.post("/v1/responses", json={"input": 1}).status_code == 400


def test_responses_length_is_incomplete() -> None:
    class Limited(FullEngine):
        def chat(self, request):  # noqa: ANN001
            return ChatResult(content="x", finish_reason="length", usage={})

    with make_client(["openai.responses"], Limited()) as client:
        body = client.post("/v1/responses", json={"input": "x"}).json()
        assert body["status"] == "incomplete"
        assert body["incomplete_details"] == {"reason": "max_output_tokens"}


# --------------------------------------------------------------------------- #
# OpenAI embeddings / moderations
# --------------------------------------------------------------------------- #


def test_embeddings_all_input_shapes_and_errors() -> None:
    with make_client(["openai.embeddings"]) as client:
        for payload in (
            {"input": "a"},
            {"input": ["a", "b"]},
            {"input": [1, 2, 3]},
            {"input": [[1, 2], [3, 4]]},
        ):
            assert client.post("/v1/embeddings", json=payload).status_code == 200

        for bad in (
            {},
            {"input": []},
            {"input": [1, "x"]},
            {"input": "a", "dimensions": 0},
            {"input": "a", "encoding_format": "int8"},
        ):
            assert client.post("/v1/embeddings", json=bad).status_code == 400

        assert client.post("/v1/embeddings", json={"input": "a"}).json()["model"] == "fake-model"

    class Short(FullEngine):
        def embed(self, request):  # noqa: ANN001
            return EmbeddingResult(embeddings=[], usage={})

    with make_client(["openai.embeddings"], Short()) as client:
        assert client.post("/v1/embeddings", json={"input": "a"}).status_code == 500


def test_moderations_inputs_and_errors() -> None:
    with make_client(["openai.moderations"]) as client:
        body = client.post("/v1/moderations", json={"input": "bad"}).json()
        assert body["results"][0]["flagged"] is True
        assert body["model"] == "fake-model"
        for bad in ({}, {"input": []}, {"input": 3}):
            assert client.post("/v1/moderations", json=bad).status_code == 400


# --------------------------------------------------------------------------- #
# OpenAI audio
# --------------------------------------------------------------------------- #


def test_audio_formats_and_errors() -> None:
    with make_client(["openai.audio.transcriptions", "openai.audio.translations"]) as client:
        files = {"file": ("a.wav", b"audio", "audio/wav")}
        assert client.post(
            "/v1/audio/transcriptions", files=files, data={"response_format": "text"}
        ).text == "transcribe:hello"
        srt = client.post(
            "/v1/audio/transcriptions", files=files, data={"response_format": "srt"}
        ).text
        assert "00:00:00,000 --> 00:00:01,500" in srt
        vtt = client.post(
            "/v1/audio/transcriptions", files=files, data={"response_format": "vtt"}
        ).text
        assert vtt.startswith("WEBVTT")
        verbose = client.post(
            "/v1/audio/transcriptions", files=files, data={"response_format": "verbose_json"}
        ).json()
        assert verbose["words"][0]["word"] == "hello"

        assert client.post("/v1/audio/transcriptions", files={"file": ("a", b"", "audio/wav")}).status_code == 400
        assert client.post("/v1/audio/transcriptions").status_code == 400


def test_speech_error_paths() -> None:
    with make_client(["openai.audio.speech"]) as client:
        assert client.post("/v1/audio/speech", json={}).status_code == 400
        response = client.post("/v1/audio/speech", json={"input": "hi", "response_format": "wav"})
        assert response.content == b"RIFF"


# --------------------------------------------------------------------------- #
# OpenAI images
# --------------------------------------------------------------------------- #


def test_images_generation_edit_variation() -> None:
    with make_client(["openai.images.generations", "openai.images.edits", "openai.images.variations"]) as client:
        assert client.post("/v1/images/generations", json={}).status_code == 400
        generated = client.post(
            "/v1/images/generations", json={"prompt": "cat", "response_format": "url"}
        ).json()
        assert generated["data"][0]["url"].startswith("data:image/png;base64,")
        assert generated["data"][0]["revised_prompt"] == "rev"

        assert client.post("/v1/images/edits", files={"image": ("i.png", b"x", "image/png")}, data={}).status_code == 400
        assert client.post("/v1/images/variations", data={}).status_code == 400
        variation = client.post(
            "/v1/images/variations",
            files={"image": ("i.png", b"x", "image/png")},
            data={"response_format": "b64_json"},
        )
        assert variation.status_code == 200
        assert variation.json()["data"][0]["b64_json"]


# --------------------------------------------------------------------------- #
# OpenAI videos
# --------------------------------------------------------------------------- #


def test_videos_multipart_and_lifecycle() -> None:
    with make_client(["openai.videos"]) as client:
        created = client.post(
            "/v1/videos",
            files={"input_reference": ("r.png", b"ref", "image/png")},
            data={"prompt": "a cat", "seconds": "4", "size": "1280x720"},
        )
        assert created.status_code == 200
        assert created.json()["id"] == "video_1"
        assert client.get("/v1/videos/video_1").json()["status"] == "completed"
        assert client.get("/v1/videos/missing").status_code == 404
        assert client.get("/v1/videos/video_1/content").content == b"mp4"
        assert client.delete("/v1/videos/video_1").json()["deleted"] is True
        assert client.delete("/v1/videos/missing").json()["deleted"] is False


def test_videos_list_endpoint() -> None:
    class ListingEngine(FullEngine):
        def list_videos(self):  # noqa: ANN001
            return [
                {"id": "v1", "status": "completed"},
                {"id": "v2", "status": "queued"},
            ]

    with make_client(["openai.videos"], ListingEngine()) as client:
        body = client.get("/v1/videos").json()
        assert body["object"] == "list"
        assert [item["id"] for item in body["data"]] == ["v1", "v2"]
        limited = client.get("/v1/videos", params={"limit": 1}).json()
        assert len(limited["data"]) == 1
        assert limited["has_more"] is True
        for bad in (0, 101, "x"):
            assert client.get("/v1/videos", params={"limit": bad}).status_code == 400

    class NoListing(FullEngine):
        list_videos = None

    with make_client(["openai.videos"], NoListing()) as client:
        assert client.get("/v1/videos").status_code == 501


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #


def test_anthropic_messages_all_blocks() -> None:
    engine = FullEngine()
    with make_client(["anthropic.messages"], engine) as client:
        body = client.post(
            "/v1/messages",
            json={
                "model": "claude-fake",
                "max_tokens": 64,
                "system": [{"type": "text", "text": "be brief"}],
                "stop_sequences": "END",
                "tools": [{"name": "lookup", "description": "d", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "tool", "name": "lookup"},
                "thinking": {"type": "enabled", "budget_tokens": 16},
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": "hi"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
                    ]},
                    {"role": "assistant", "content": [
                        {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"q": "x"}}
                    ]},
                    {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                        {"type": "document", "source": {"type": "base64", "data": "doc"}},
                        {"type": "redacted_thinking", "data": "secret"},
                    ]},
                ],
            },
        )
        assert body.status_code == 200
        payload = body.json()
        assert payload["type"] == "message"
        assert payload["model"] == "claude-fake"
        assert payload["stop_reason"] == "tool_use"
        assert payload["usage"] == {"input_tokens": 3, "output_tokens": 4}
        assert [b["type"] for b in payload["content"]] == ["thinking", "text", "tool_use"]
        assert payload["content"][2]["input"] == {"q": "x"}

        sent = engine.requests[-1]
        assert sent.messages[0].role == "system"
        assert sent.messages[0].content == "be brief"
        assert sent.tools[0]["function"]["name"] == "lookup"
        assert sent.tools[0]["function"]["parameters"] == {"type": "object"}
        assert sent.stop == ["END"]
        assert sent.extras["anthropic_thinking"]["budget_tokens"] == 16
        assert sent.extras["enable_thinking"] is True


def test_anthropic_preserves_cache_control_and_tool_result_images() -> None:
    engine = FullEngine()
    cache = {"type": "ephemeral"}
    with make_client(["anthropic.messages"], engine) as client:
        response = client.post(
            "/v1/messages",
            json={
                "max_tokens": 16,
                "system": [{"type": "text", "text": "sys", "cache_control": cache}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hi", "cache_control": cache}
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "t1",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "ok",
                                        "cache_control": cache,
                                    },
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": "AAA",
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                ],
            },
        )
        assert response.status_code == 200
        sent = engine.requests[-1]
        assert sent.messages[0].role == "system"
        assert isinstance(sent.messages[0].content, list)
        assert sent.messages[0].content[0]["cache_control"] == cache

        user = sent.messages[1]
        assert isinstance(user.content, list)
        assert user.content[0]["cache_control"] == cache

        tool = sent.messages[2]
        assert tool.role == "tool"
        assert isinstance(tool.content, list)
        assert tool.content[0]["cache_control"] == cache
        assert any(part.get("type") == "image_url" for part in tool.content)


def test_anthropic_stream_and_errors() -> None:
    with make_client(["anthropic.messages"]) as client:
        text = client.post(
            "/v1/messages",
            json={"max_tokens": 8, "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        ).text
        events = [line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")]
        for event in ("message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"):
            assert event in events
        assert "thinking_delta" in text
        assert "text_delta" in text
        assert "input_json_delta" in text

        for bad in (
            {},
            {"messages": []},
            {"messages": [{"role": "user", "content": [{"type": "bogus"}]}]},
            {"messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "x"}}]}]},
            {"messages": [{"role": "user", "content": [{"type": "tool_use", "name": ""}]}]},
            {"messages": [{"role": "user", "content": [{"type": "tool_result"}]}]},
            {"messages": [{"role": "user", "content": "x"}], "tools": [{"description": "no name"}]},
        ):
            assert client.post("/v1/messages", json=bad).status_code == 400


def test_anthropic_count_tokens_errors() -> None:
    class Boom(FullEngine):
        def count_tokens(self, request):  # noqa: ANN001
            raise RuntimeError("nope")

    with make_client(["anthropic.count_tokens"], Boom()) as client:
        response = client.post(
            "/v1/messages/count_tokens",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 500
        assert response.json()["type"] == "error"


# --------------------------------------------------------------------------- #
# Realtime
# --------------------------------------------------------------------------- #


def test_realtime_delegation_and_handler_error() -> None:
    with make_client(["openai.realtime"]) as client:
        with client.websocket_connect("/v1/realtime?model=chosen") as ws:
            assert ws.receive_json() == {"type": "session.created", "model": "chosen"}

    class Boom(FullEngine):
        async def realtime_session(self, websocket, model):  # noqa: ANN001
            raise RuntimeError("boom")

    with make_client(["openai.realtime"], Boom()) as client:
        with client.websocket_connect("/v1/realtime") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert message["error"]["type"] == "api_error"


# --------------------------------------------------------------------------- #
# capability gating / registry
# --------------------------------------------------------------------------- #


def test_legacy_default_and_explicit_empty_gating() -> None:
    with TestClient(build_app(FullEngine())) as client:
        assert client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
        ).status_code == 200
        assert client.post("/v1/messages", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 404

    with make_client([]) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/models").status_code == 200
        assert client.post("/v1/completions", json={"prompt": "x"}).status_code == 404
        assert client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
        ).status_code == 404


def test_all_capabilities_mount_expected_routes() -> None:
    with make_client(ALL_CAPS) as client:
        paths = {
            "/v1/chat/completions",
            "/v1/completions",
            "/v1/responses",
            "/v1/embeddings",
            "/v1/moderations",
            "/v1/audio/transcriptions",
            "/v1/audio/translations",
            "/v1/audio/speech",
            "/v1/images/generations",
            "/v1/images/edits",
            "/v1/images/variations",
            "/v1/videos",
            "/v1/videos/{video_id}",
            "/v1/videos/{video_id}/content",
            "/v1/messages",
            "/v1/messages/count_tokens",
            "/v1/models/{model_id}",
        }
        routes = {route.path for route in client.app.routes if hasattr(route, "path")}
        assert paths <= routes
        assert "/v1/realtime" in routes


def test_planned_capability_returns_501(monkeypatch: pytest.MonkeyPatch) -> None:
    from flashcli_bundle.infer.serve.protocols import registry

    monkeypatch.setattr(
        registry, "PLANNED_HTTP", {"openai.future": ("POST", "/v1/future")}
    )
    with make_client(["openai.future"]) as client:
        response = client.post("/v1/future")
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "capability_not_implemented"


def test_capability_parsing_and_validation() -> None:
    assert parse_serve_capabilities(None) == (
        None,
        "serve.capabilities must be an array of strings",
    )
    assert parse_serve_capabilities([" openai.chat "]) == (["openai.chat"], None)
    assert parse_serve_capabilities([1])[0] is None
    assert parse_serve_capabilities(["  "])[0] is None

    assert effective_serve_capabilities(None) == []
    native = EntrySpec.from_dict({"kind": "native-exec", "module": "", "attr": "", "native": {"command": ["x"]}})
    assert native is not None and effective_serve_capabilities(native) == []
    script = EntrySpec.from_dict(
        {"kind": "python", "module": "m", "attr": "E", "mode": "script"}
    )
    assert script is not None and effective_serve_capabilities(script) == []
    no_caps = EntrySpec.from_dict(
        {"kind": "python", "module": "m", "attr": "E", "mode": "engine"}
    )
    assert no_caps is not None and effective_serve_capabilities(no_caps) == ["openai.chat"]

    assert validate_serve_capabilities(None) == []
    invalid = EntrySpec.from_dict(
        {
            "kind": "python",
            "module": "m",
            "attr": "E",
            "mode": "engine",
            "capabilities": ["openai.chat", "openai.chat", "nope"],
        }
    )
    assert invalid is not None
    joined = "\n".join(validate_serve_capabilities(invalid))
    assert "duplicate" in joined and "unknown" in joined


# --------------------------------------------------------------------------- #
# protocol gap regressions
# --------------------------------------------------------------------------- #


def test_chat_forwards_tool_choice_and_sampling_extras() -> None:
    engine = FullEngine()
    with make_client(["openai.chat"], engine) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
                "tool_choice": {"type": "function", "function": {"name": "f"}},
                "response_format": {"type": "json_object"},
                "frequency_penalty": 0.5,
                "presence_penalty": 0.1,
                "logprobs": True,
                "user": "u1",
            },
        )
        assert response.status_code == 200
        extras = engine.requests[0].extras
        assert extras["tool_choice"] == {"type": "function", "function": {"name": "f"}}
        assert extras["response_format"] == {"type": "json_object"}
        assert extras["frequency_penalty"] == 0.5
        assert extras["presence_penalty"] == 0.1
        assert extras["logprobs"] is True
        assert extras["user"] == "u1"


def test_chat_n_multiple_choices_and_errors() -> None:
    engine = FullEngine()
    with make_client(["openai.chat"], engine) as client:
        body = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "n": 3},
        ).json()
        assert [choice["index"] for choice in body["choices"]] == [0, 1, 2]
        assert len(engine.requests) == 3
        assert body["usage"]["total_tokens"] == 21

        for bad in (0, -1, "abc"):
            assert client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}], "n": bad},
            ).status_code == 400
        streamed = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "n": 2, "stream": True},
        )
        assert streamed.status_code == 200
        assert '"index": 1' in streamed.text
        assert "[DONE]" in streamed.text


def test_anthropic_tool_choice_mapping() -> None:
    engine = FullEngine()
    with make_client(["anthropic.messages"], engine) as client:
        cases = [
            ({"type": "auto"}, "auto"),
            ({"type": "any"}, "required"),
            ({"type": "none"}, "none"),
            ({"type": "tool", "name": "lookup"}, {"type": "function", "function": {"name": "lookup"}}),
        ]
        for choice, expected in cases:
            response = client.post(
                "/v1/messages",
                json={
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "hi"}],
                    "tool_choice": choice,
                },
            )
            assert response.status_code == 200
            assert engine.requests[-1].extras["tool_choice"] == expected


def test_responses_forwards_control_params() -> None:
    engine = FullEngine()
    with make_client(["openai.responses"], engine) as client:
        response = client.post(
            "/v1/responses",
            json={
                "input": "hi",
                "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
                "tool_choice": {"type": "function", "name": "lookup"},
                "reasoning": {"effort": "low"},
                "truncation": "auto",
                "parallel_tool_calls": False,
            },
        )
        assert response.status_code == 200
        extras = engine.requests[-1].extras
        assert extras["tool_choice"] == {"type": "function", "function": {"name": "lookup"}}
        assert extras["reasoning"] == {"effort": "low"}
        assert extras["truncation"] == "auto"
        assert extras["parallel_tool_calls"] is False


def test_audio_translation_verbose_json_task() -> None:
    with make_client(["openai.audio.translations"]) as client:
        body = client.post(
            "/v1/audio/translations",
            files={"file": ("a.wav", b"x", "audio/wav")},
            data={"response_format": "verbose_json"},
        ).json()
        assert body["task"] == "translate"


def test_anthropic_models_pagination() -> None:
    headers = {"anthropic-version": "2023-06-01"}
    with make_client(["anthropic.models"]) as client:
        assert len(client.get("/v1/models", headers=headers, params={"limit": 1}).json()["data"]) == 1
        assert client.get("/v1/models", headers=headers, params={"after_id": "fake-model"}).json()["data"] == []
        assert client.get("/v1/models", headers=headers, params={"before_id": "fake-model"}).json()["data"] == []
        for bad in (0, 1001, "x"):
            assert client.get("/v1/models", headers=headers, params={"limit": bad}).status_code == 400


# --------------------------------------------------------------------------- #
# inference gate
# --------------------------------------------------------------------------- #


def test_inference_gate_busy_timeout_and_run() -> None:
    async def scenario() -> None:
        gate = InferenceGate(busy_timeout=0.01)
        await gate.acquire("a")
        assert gate.is_busy is True
        assert gate.busy_holder == "a"
        with pytest.raises(GpuBusyError):
            await gate.acquire("b")
        gate.release()
        assert gate.is_busy is False

        async def work() -> str:
            return "done"

        assert await gate.run("c", work()) == "done"

    asyncio.run(scenario())


def test_iter_on_inference_loop_yields_and_propagates() -> None:
    async def scenario() -> None:
        seen: list[int] = []

        async def factory():  # noqa: ANN202
            for i in range(3):
                yield i

        async for value in iter_on_inference_loop(factory):
            seen.append(value)
        assert seen == [0, 1, 2]

        async def broken():  # noqa: ANN202
            yield 1
            raise RuntimeError("stream boom")

        with pytest.raises(RuntimeError, match="stream boom"):
            async for _ in iter_on_inference_loop(broken):
                pass

    asyncio.run(scenario())
