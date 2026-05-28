"""Single-slot GPU inference gate and thread-pool offload for serve."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class GpuBusyError(Exception):
    """Raised when the inference slot cannot be acquired within the busy timeout."""


def default_busy_timeout_sec() -> float:
    raw = os.environ.get("FLASHCLI_SERVE_BUSY_TIMEOUT_SEC", "0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


class InferenceGate:
    """Batch-1 inference slot: one GPU job at a time; fast reject when busy."""

    def __init__(self, *, busy_timeout: float | None = None) -> None:
        self._sem = asyncio.Semaphore(1)
        self._busy_timeout = (
            busy_timeout if busy_timeout is not None else default_busy_timeout_sec()
        )
        self._holder: str | None = None
        self._acquired = False

    @property
    def is_busy(self) -> bool:
        return self._acquired

    @property
    def busy_holder(self) -> str | None:
        return self._holder

    async def acquire(self, request_id: str) -> None:
        timeout = self._busy_timeout
        try:
            if timeout <= 0:
                await asyncio.wait_for(self._sem.acquire(), timeout=0.001)
            else:
                await asyncio.wait_for(self._sem.acquire(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise GpuBusyError(
                "GPU inference slot is busy (another request is running)."
            ) from exc
        self._holder = request_id
        self._acquired = True

    def release(self) -> None:
        self._holder = None
        self._acquired = False
        self._sem.release()

    async def run(self, request_id: str, coro: Awaitable[T]) -> T:
        await self.acquire(request_id)
        try:
            return await run_awaitable_in_thread(coro)
        finally:
            self.release()


async def run_awaitable_in_thread(coro: Awaitable[T]) -> T:
    return await asyncio.to_thread(_run_coro_in_fresh_loop, coro)


def _run_coro_in_fresh_loop(coro: Awaitable[T]) -> T:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


async def iter_async_in_thread(
    factory: Callable[[], AsyncIterator[T]],
    *,
    main_loop: asyncio.AbstractEventLoop,
) -> AsyncIterator[T]:
    """Bridge an async iterator produced in a worker thread back to the main loop."""
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def worker() -> None:
        child = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(child)

            async def produce() -> None:
                try:
                    async for item in factory():
                        fut = asyncio.run_coroutine_threadsafe(
                            queue.put(("item", item)), main_loop
                        )
                        fut.result()
                    fut = asyncio.run_coroutine_threadsafe(
                        queue.put(("done", None)), main_loop
                    )
                    fut.result()
                except Exception as exc:
                    fut = asyncio.run_coroutine_threadsafe(
                        queue.put(("error", exc)), main_loop
                    )
                    fut.result()

            child.run_until_complete(produce())
        finally:
            try:
                child.run_until_complete(child.shutdown_asyncgens())
            except Exception:
                pass
            child.close()
            asyncio.set_event_loop(None)

    task = asyncio.create_task(asyncio.to_thread(worker))
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "item":
                yield payload
            elif kind == "done":
                break
            elif kind == "error":
                raise payload
    finally:
        await task
