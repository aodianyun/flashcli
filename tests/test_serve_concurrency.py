"""Concurrency config, gate behavior, and per-capability route mounting."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from flashcli_bundle.capabilities import (
    effective_serve_concurrency,
    validate_serve_concurrency,
)
from flashcli_bundle.manifest import EntrySpec
from flashcli_bundle.protocol import EmbeddingResult

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx  # noqa: E402

from flashcli_bundle.infer.serve.app import build_app  # noqa: E402


def _serve(**overrides):
    data = {"kind": "python", "module": "serve", "attr": "ServeEngine", "mode": "engine"}
    data.update(overrides)
    return EntrySpec.from_dict(data)


def test_concurrency_parsing_and_defaults() -> None:
    assert effective_serve_concurrency(_serve()) == 1
    assert effective_serve_concurrency(_serve(concurrency=2)) == 2
    spec = _serve(concurrency=0)
    assert spec is not None
    assert validate_serve_concurrency(spec)
    spec = _serve(concurrency=True)
    assert spec is not None
    assert validate_serve_concurrency(spec)
    script = _serve(mode="script", concurrency=2)
    assert script is not None
    assert "only valid for python engine serve" in "\n".join(
        validate_serve_concurrency(script)
    )
    assert "gated" in "\n".join(
        validate_serve_concurrency(_serve(capabilities=[], concurrency=2))
    )
    assert "gated" in "\n".join(
        validate_serve_concurrency(
            _serve(capabilities=["anthropic.count_tokens"], concurrency=2)
        )
    )
    assert not validate_serve_concurrency(
        _serve(capabilities=["openai.chat"], concurrency=2)
    )


class _BaseEngine:
    model_id = "m"

    def load(self, checkpoint: Path, preset) -> None:  # noqa: ANN001
        del checkpoint, preset

    def warmup(self, spec: str | None) -> None:
        del spec


class _HoldEngine(_BaseEngine):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def embed(self, req) -> EmbeddingResult:  # noqa: ANN001
        self.calls += 1
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return EmbeddingResult(embeddings=[[0.0] for _ in req.input])


async def _embed(client: httpx.AsyncClient, text: str):
    return await client.post("/v1/embeddings", json={"input": text, "model": "m"})


async def _wait_started(engine: _HoldEngine) -> None:
    for _ in range(200):
        if engine.started.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("engine did not start")


async def _run_pair(concurrency: int, monkeypatch) -> tuple[int, int]:
    monkeypatch.setenv("FLASHCLI_SERVE_BUSY_TIMEOUT_SEC", "0")
    engine = _HoldEngine()
    app = build_app(
        engine,
        serve_capabilities=["openai.embeddings"],
        serve_concurrency=concurrency,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        first = asyncio.create_task(_embed(client, "a"))
        await _wait_started(engine)
        second = asyncio.create_task(_embed(client, "b"))
        if concurrency == 1:
            second_response = await asyncio.wait_for(second, timeout=1.0)
            second_status = second_response.status_code
            engine.release.set()
        else:
            await _wait_until_calls(engine, 2)
            engine.release.set()
            second_status = (await asyncio.wait_for(second, timeout=2.0)).status_code
        first_status = (await asyncio.wait_for(first, timeout=2.0)).status_code
    return first_status, second_status


async def _wait_until_calls(engine: _HoldEngine, count: int) -> None:
    for _ in range(200):
        if engine.calls >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"engine did not reach {count} calls")


def test_single_slot_rejects_second_request(monkeypatch) -> None:
    first, second = asyncio.run(_run_pair(1, monkeypatch))
    assert first == 200
    assert second == 503


def test_configured_concurrency_allows_overlap(monkeypatch) -> None:
    first, second = asyncio.run(_run_pair(2, monkeypatch))
    assert first == 200
    assert second == 200


def _paths(caps: list[str]) -> set[str]:
    app = build_app(_BaseEngine(), serve_capabilities=caps, serve_concurrency=1)
    return {route.path for route in app.routes}


def test_audio_capabilities_mount_their_own_routes() -> None:
    transcriptions = _paths(["openai.audio.transcriptions"])
    assert "/v1/audio/transcriptions" in transcriptions
    assert "/v1/audio/translations" not in transcriptions

    translations = _paths(["openai.audio.translations"])
    assert "/v1/audio/translations" in translations
    assert "/v1/audio/transcriptions" not in translations


def test_image_capabilities_mount_their_own_routes() -> None:
    generations = _paths(["openai.images.generations"])
    assert "/v1/images/generations" in generations
    assert "/v1/images/edits" not in generations
    assert "/v1/images/variations" not in generations

    edits = _paths(["openai.images.edits"])
    assert "/v1/images/edits" in edits
    assert "/v1/images/generations" not in edits
    assert "/v1/images/variations" not in edits
