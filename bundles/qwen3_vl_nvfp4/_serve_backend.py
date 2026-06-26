"""Shared serve-backend helpers for qwen3_vl_nvfp4."""

from __future__ import annotations

import asyncio
import logging
import queue as thread_queue
import threading
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult

log = logging.getLogger(__name__)

_SENTINEL = object()
_STREAM_JOIN_TIMEOUT_S = 120.0


@runtime_checkable
class ServeChatBackend(Protocol):
    async def chat_async(self, req: ChatRequest) -> ChatResult: ...

    def chat_stream_async(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...

    def warmup(self, max_new_tokens: int = 0, **kwargs: Any) -> None: ...

    def register_routes(self, app: Any) -> None: ...


def flashrt_extensions_from_usage(usage: dict[str, Any]) -> dict[str, Any]:
    if not usage:
        return {}
    keys = (
        "prefill_ms",
        "decode_ms",
        "ttft_ms",
        "first_delta_ms",
        "wall_s",
        "tok_per_s",
        "decode_tok_per_s",
    )
    block = {k: usage[k] for k in keys if usage.get(k) is not None}
    return {"flashrt": block} if block else {}
