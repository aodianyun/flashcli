"""Shared serve-backend protocol for qwen_nvfp4 (and future LLM bundles)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable

from flashcli.engines.base import ChatChunk, ChatRequest, ChatResult


@runtime_checkable
class ServeChatBackend(Protocol):
    """Minimal surface required by ``bundles/qwen_nvfp4/serve.py``."""

    async def chat_async(self, req: ChatRequest) -> ChatResult: ...

    def chat_stream_async(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...

    def warmup(self, shapes: list[tuple[int, int]], **kwargs: Any) -> None: ...

    def register_routes(self, app: Any) -> None: ...


def flashrt_extensions_from_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """Map engine timing fields into a top-level ``flashrt`` response block."""
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
        "route",
        "cached_tokens",
        "session_id",
        "prefix_action",
    )
    block = {k: usage[k] for k in keys if usage.get(k) is not None}
    return {"flashrt": block} if block else {}


async def bridge_sync_chunk_iterator(
    producer: Any,
) -> AsyncIterator[ChatChunk]:
    """Run a blocking sync chunk iterator on a worker thread (qwen36 agent)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
    sentinel = object()

    def _run() -> None:
        try:
            for chunk in producer():
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop).result()

    threading.Thread(target=_run, daemon=True).start()
    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, Exception):
            raise item
        yield item
