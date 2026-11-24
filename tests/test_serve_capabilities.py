"""Serve capability parsing, validation, and host route gating."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli_bundle.capabilities import (
    ANTHROPIC_MESSAGES,
    LEGACY_SERVE_CAPABILITIES,
    OPENAI_CHAT,
    effective_serve_capabilities,
    validate_serve_capabilities,
)
from flashcli_bundle.manifest import EntrySpec
from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult


def _serve(caps=None, **overrides):
    data = {"kind": "python", "module": "serve", "attr": "ServeEngine", "mode": "engine"}
    if caps is not None:
        data["capabilities"] = caps
    data.update(overrides)
    return EntrySpec.from_dict(data)


def test_legacy_manifest_defaults_to_openai_chat() -> None:
    spec = _serve()
    assert spec is not None
    assert spec.capabilities is None
    assert effective_serve_capabilities(spec) == list(LEGACY_SERVE_CAPABILITIES)


def test_explicit_empty_disables_host_routes() -> None:
    spec = _serve([])
    assert spec is not None
    assert spec.capabilities == []
    assert effective_serve_capabilities(spec) == []


def test_explicit_capabilities_are_kept() -> None:
    spec = _serve([OPENAI_CHAT, ANTHROPIC_MESSAGES])
    assert spec is not None
    assert effective_serve_capabilities(spec) == [OPENAI_CHAT, ANTHROPIC_MESSAGES]


def test_invalid_capability_value_is_reported() -> None:
    spec = _serve("openai.chat")
    assert spec is not None
    errors = validate_serve_capabilities(spec)
    assert errors and "must be an array" in errors[0]


def test_unknown_and_duplicate_capabilities_fail() -> None:
    spec = _serve(["openai.chat", "openai.chat", "bogus.protocol"])
    assert spec is not None
    joined = "\n".join(validate_serve_capabilities(spec))
    assert "duplicate" in joined
    assert "unknown" in joined


def test_capabilities_require_python_engine_serve() -> None:
    script = _serve([OPENAI_CHAT], mode="script")
    assert script is not None
    assert "only valid for python engine serve" in "\n".join(
        validate_serve_capabilities(script)
    )
    native = EntrySpec.from_dict(
        {"kind": "native-exec", "module": "", "attr": "", "native": {"command": ["x"]}}
    )
    assert native is not None
    native = EntrySpec(
        module="", attr="", mode="engine", kind="native-exec", capabilities=[OPENAI_CHAT],
        capabilities_invalid=None,
    )
    assert "only valid for python engine serve" in "\n".join(
        validate_serve_capabilities(native)
    )


class _Engine:
    model_id = "fake"

    def load(self, checkpoint: Path, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec

    def chat(self, request: ChatRequest) -> ChatResult:
        del request
        return ChatResult(content="ok")

    def chat_stream(self, request: ChatRequest):
        del request
        yield ChatChunk(content_delta="ok", finish_reason="stop")


def _paths(caps, engine=None):
    pytest.importorskip("fastapi")
    from flashcli_bundle.infer.serve.app import build_app

    app = build_app(engine or _Engine(), serve_capabilities=caps)
    return {route.path for route in app.routes}


def test_host_gates_chat_route() -> None:
    paths = _paths([])
    assert "/health" in paths
    assert "/v1/models" in paths
    assert "/v1/chat/completions" not in paths

    paths = _paths([OPENAI_CHAT])
    assert "/v1/chat/completions" in paths


class _CustomEngine(_Engine):
    def register_routes(self, app) -> None:  # noqa: ANN001
        @app.get("/custom")
        async def custom():
            return {"ok": True}


def test_register_routes_survives_capability_gating() -> None:
    paths = _paths([], engine=_CustomEngine())
    assert "/custom" in paths
    assert "/v1/chat/completions" not in paths
    assert "/health" in paths
    assert "/v1/models" in paths


class _ModalityEngine:
    model_id = "m"

    def load(self, checkpoint, preset, **options) -> None:  # noqa: ANN001
        pass

    def warmup(self, spec: str | None) -> None:
        pass

    def speech(self, request):  # noqa: ANN001, ANN201
        return None


class _RealtimeEngine(_ModalityEngine):
    async def realtime_session(self, websocket, model) -> None:  # noqa: ANN001
        pass


class _FullModalityEngine(_ModalityEngine):
    def embed(self, request):  # noqa: ANN001, ANN201
        return None

    def moderate(self, request):  # noqa: ANN001, ANN201
        return None

    def transcribe(self, request):  # noqa: ANN001, ANN201
        return None

    def generate_images(self, request):  # noqa: ANN001, ANN201
        return None

    def create_video(self, request):  # noqa: ANN001, ANN201
        return {"id": "v"}

    def list_videos(self):  # noqa: ANN201
        return []

    def get_video(self, video_id):  # noqa: ANN001, ANN201
        return {"id": video_id}

    def download_video(self, video_id):  # noqa: ANN001, ANN201
        return b""

    def delete_video(self, video_id):  # noqa: ANN001, ANN201
        return True

    def count_tokens(self, request):  # noqa: ANN001, ANN201
        return 0


def test_engine_contract_depends_on_capabilities() -> None:
    from flashcli_bundle.protocol import coerce_serve_engine

    assert coerce_serve_engine(
        _ModalityEngine(), capabilities=["openai.audio.speech"]
    )
    with pytest.raises(TypeError):
        coerce_serve_engine(_ModalityEngine(), capabilities=None)
    with pytest.raises(TypeError):
        coerce_serve_engine(_ModalityEngine(), capabilities=["openai.chat"])
    assert coerce_serve_engine(
        _RealtimeEngine(), capabilities=["openai.realtime"]
    )
    with pytest.raises(TypeError):
        coerce_serve_engine(_ModalityEngine(), capabilities=["openai.realtime"])


def test_declared_modality_capabilities_require_methods() -> None:
    from flashcli_bundle.protocol import coerce_serve_engine

    caps = [
        "openai.embeddings",
        "openai.moderations",
        "openai.audio.transcriptions",
        "openai.audio.translations",
        "openai.images.generations",
        "openai.images.edits",
        "openai.images.variations",
        "openai.videos",
        "anthropic.count_tokens",
    ]
    for cap in caps:
        with pytest.raises(TypeError):
            coerce_serve_engine(_ModalityEngine(), capabilities=[cap])
        assert coerce_serve_engine(_FullModalityEngine(), capabilities=[cap])
    with pytest.raises(TypeError):
        coerce_serve_engine(
            _RealtimeEngine(), capabilities=["openai.realtime", "openai.embeddings"]
        )
