"""OpenAI moderation and async video host route tests."""

from __future__ import annotations

import pytest

from flashcli_bundle.protocol import ModerationRequest, ModerationResult, VideoRequest


class _Engine:
    model_id = "fake"

    def __init__(self) -> None:
        self.videos: dict[str, bytes] = {}

    def load(self, checkpoint, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request):  # noqa: ANN001
        raise NotImplementedError

    def chat_stream(self, request):  # noqa: ANN001
        yield  # pragma: no cover

    def moderate(self, request: ModerationRequest) -> ModerationResult:
        return ModerationResult(
            results=[
                {
                    "flagged": "bad" in text,
                    "categories": {"harassment": "bad" in text},
                    "category_scores": {"harassment": 1.0 if "bad" in text else 0.0},
                }
                for text in request.input
            ],
            usage={"total_tokens": len(request.input)},
        )

    def create_video(self, request: VideoRequest) -> dict:
        video_id = "video_1"
        self.videos[video_id] = b"mp4"
        return {"id": video_id, "status": "queued", "model": request.model, "prompt": request.prompt}

    def get_video(self, video_id: str) -> dict:
        if video_id not in self.videos:
            raise KeyError(video_id)
        return {"id": video_id, "status": "completed", "object": "video"}

    def download_video(self, video_id: str) -> bytes:
        return self.videos[video_id]

    def delete_video(self, video_id: str) -> bool:
        return self.videos.pop(video_id, None) is not None


def _client(caps, engine=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from flashcli_bundle.infer.serve.app import build_app

    return TestClient(build_app(engine or _Engine(), serve_capabilities=caps))


def test_moderations() -> None:
    with _client(["openai.moderations"]) as client:
        response = client.post("/v1/moderations", json={"model": "fake", "input": ["ok", "bad"]})
        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "fake"
        assert [r["flagged"] for r in body["results"]] == [False, True]


def test_video_job_lifecycle() -> None:
    with _client(["openai.videos"]) as client:
        created = client.post("/v1/videos", json={"model": "fake", "prompt": "a cat"})
        assert created.status_code == 200
        video_id = created.json()["id"]
        assert client.get(f"/v1/videos/{video_id}").json()["status"] == "completed"
        content = client.get(f"/v1/videos/{video_id}/content")
        assert content.status_code == 200
        assert content.content == b"mp4"
        deleted = client.delete(f"/v1/videos/{video_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/v1/videos/{video_id}").status_code == 404


def test_moderation_and_video_501_without_engine_methods() -> None:
    class Empty(_Engine):
        moderate = None
        create_video = None
        get_video = None
        download_video = None
        delete_video = None

    with _client(["openai.moderations", "openai.videos"], engine=Empty()) as client:
        assert client.post("/v1/moderations", json={"input": "x"}).status_code == 501
        assert client.post("/v1/videos", json={"prompt": "x"}).status_code == 501
        assert client.get("/v1/videos/x").status_code == 501


def test_moderation_and_video_are_gated() -> None:
    with _client([]) as client:
        assert client.post("/v1/moderations", json={"input": "x"}).status_code == 404
        assert client.post("/v1/videos", json={"prompt": "x"}).status_code == 404
