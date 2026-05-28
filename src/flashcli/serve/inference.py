"""Single-slot GPU inference gate and dedicated asyncio loop for serve."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

_loop_holder: InferenceLoop | None = None
_loop_init = threading.Lock()


class GpuBusyError(Exception):
    """Raised when the inference slot cannot be acquired within the busy timeout."""


def default_busy_timeout_sec() -> float:
    raw = os.environ.get("FLASHCLI_SERVE_BUSY_TIMEOUT_SEC", "0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


class InferenceLoop:
    """One persistent background event loop for FlashRT async engines (Qwen Lock)."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("InferenceLoop not started")
        return self._loop

    def start(self) -> None:
        if self._thread is not None:
            return

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(
            target=_thread_main,
            name="flashcli-inference-loop",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=60.0):
            raise RuntimeError("InferenceLoop failed to start within 60s")

    async def run(self, coro: Awaitable[T]) -> T:
        self.start()
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return await asyncio.wrap_future(fut)


def get_inference_loop() -> InferenceLoop:
    global _loop_holder
    with _loop_init:
        if _loop_holder is None:
            _loop_holder = InferenceLoop()
            _loop_holder.start()
        return _loop_holder


class InferenceGate:
    """Batch-1 inference slot on the HTTP event loop (batch=1 GPU jobs)."""

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
            return await get_inference_loop().run(coro)
        finally:
            self.release()


async def run_on_inference_loop(coro: Awaitable[T]) -> T:
    return await get_inference_loop().run(coro)


async def iter_on_inference_loop(
    factory: Callable[[], AsyncIterator[T]],
) -> AsyncIterator[T]:
    """Run an async chunk iterator on the dedicated inference loop."""
    inf = get_inference_loop()
    main_loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for item in factory():
                await asyncio.wrap_future(
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("item", item)), main_loop
                    )
                )
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    queue.put(("done", None)), main_loop
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    queue.put(("error", exc)), main_loop
                )
            )

    produce_fut = asyncio.run_coroutine_threadsafe(produce(), inf.loop)
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
        if not produce_fut.done():
            produce_fut.cancel()
