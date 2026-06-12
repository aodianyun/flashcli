"""Shared serve-backend protocol for qwen_nvfp4 (and future LLM bundles)."""

from __future__ import annotations

import asyncio
import logging
import queue as thread_queue
import threading
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult

log = logging.getLogger(__name__)

_SENTINEL = object()

# Max wait for GPU stream thread after client disconnect (ctrl+c on curl).
_STREAM_JOIN_TIMEOUT_S = 120.0


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


def _queue_put(q: thread_queue.Queue[Any], item: Any, *, cancel: threading.Event) -> None:
    while not cancel.is_set():
        try:
            q.put(item, timeout=0.25)
            return
        except thread_queue.Full:
            continue
    try:
        q.put(item, timeout=1.0)
    except thread_queue.Full:
        pass


async def bridge_sync_chunk_iterator(
    producer: Any,
    *,
    join_timeout_s: float = _STREAM_JOIN_TIMEOUT_S,
) -> AsyncIterator[ChatChunk]:
    """Run a blocking sync chunk iterator on a worker thread (qwen36 agent).

    Uses a thread-safe ``queue.Queue`` (not ``asyncio.Queue`` + ``.result()``) so
    client disconnect during SSE does not deadlock the event loop. On disconnect,
    the sync generator is closed and we join the worker before the HTTP handler
    releases the inference gate.
    """
    cancel = threading.Event()
    out_q: thread_queue.Queue[Any] = thread_queue.Queue(maxsize=64)

    def _run() -> None:
        gen = producer()
        try:
            for chunk in gen:
                if cancel.is_set():
                    break
                _queue_put(out_q, chunk, cancel=cancel)
        except Exception as exc:
            if not cancel.is_set():
                _queue_put(out_q, exc, cancel=cancel)
        finally:
            close_fn = getattr(gen, "close", None)
            if close_fn is not None:
                try:
                    close_fn()
                except Exception:
                    pass
            _queue_put(out_q, _SENTINEL, cancel=cancel)

    thread = threading.Thread(
        target=_run,
        name="flashcli-stream-producer",
        daemon=True,
    )
    thread.start()
    try:
        while True:
            item = await asyncio.to_thread(out_q.get)
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        cancel.set()
        drained = 0
        while True:
            try:
                out_q.get_nowait()
                drained += 1
            except thread_queue.Empty:
                break
        if drained:
            log.debug("drained %d queued stream chunk(s) after cancel", drained)
        await asyncio.to_thread(thread.join, join_timeout_s)
        if thread.is_alive():
            log.warning(
                "stream producer thread still running after client disconnect "
                "(%.0fs join timeout); next request may hang until it finishes — "
                "restart flashcli serve if needed",
                join_timeout_s,
            )
