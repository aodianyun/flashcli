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
