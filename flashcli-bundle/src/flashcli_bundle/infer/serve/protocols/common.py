"""Shared helpers for host-owned protocol routes."""

from __future__ import annotations

import inspect
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException

from flashcli_bundle.infer.engines.base import ChatChunk, ChatRequest, ChatResult
from flashcli_bundle.infer.serve.inference import GpuBusyError, InferenceGate, iter_on_inference_loop


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


def now() -> int:
    return int(time.time())


def sse(data: Any) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def gpu_busy(model_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": {
                "message": "GPU inference slot is busy; retry after the current request finishes.",
                "type": "server_busy",
                "code": "gpu_busy",
                "model": model_id,
            }
        },
        headers={"Retry-After": "5"},
    )


async def chat_once(gate: InferenceGate, engine: Any, request_id: str, req: ChatRequest) -> ChatResult:
    async def _run() -> ChatResult:
        if hasattr(engine, "chat_async"):
            return await engine.chat_async(req)
        result = engine.chat(req)
        if inspect.isawaitable(result):
            result = await result
        return result

    try:
        return await gate.run(request_id, _run())
    except GpuBusyError:
        raise gpu_busy(engine.model_id) from None


async def call_engine(
    gate: InferenceGate,
    engine: Any,
    request_id: str,
    method: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run one engine method on the inference loop behind the shared gate.

    Sync engine methods run on the dedicated inference-loop thread; async
    methods are awaited there. The gate size comes from ``serve.concurrency``,
    so multiple requests can overlap when the bundle declares it and implements
    async (or otherwise thread-safe) methods.
    """

    async def _call() -> Any:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    try:
        return await gate.run(request_id, _call())
    except GpuBusyError:
        raise gpu_busy(engine.model_id) from None


async def chat_chunks(engine: Any, req: ChatRequest) -> AsyncIterator[ChatChunk]:
    async def _iter():
        if hasattr(engine, "chat_stream_async"):
            async for chunk in engine.chat_stream_async(req):
                yield chunk
            return
        for chunk in engine.chat_stream(req):
            yield chunk

    async for chunk in iter_on_inference_loop(lambda: _iter()):
        yield chunk
