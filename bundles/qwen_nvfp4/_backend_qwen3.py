"""Qwen3 backend — FlashRT ``examples/qwen3_openai_server.Qwen3Engine``."""

from __future__ import annotations

from typing import Any, AsyncIterator

from flashcli.engines.base import ChatChunk, ChatRequest, ChatResult

from _flashrt_qwen3 import import_qwen3_engine_class
from _qwen_util import messages_from_request
from _serve_backend import flashrt_extensions_from_usage


class Qwen3Backend:
    """Unified ``ChatRequest`` / ``ChatResult`` adapter over ``Qwen3Engine``."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.model_name = str(engine.model_name)

    @classmethod
    def from_checkpoint(
        cls,
        *,
        checkpoint: str,
        device: str,
        model_name: str,
        max_seq: int,
        max_q_seq: int,
    ) -> Qwen3Backend:
        EngineCls = import_qwen3_engine_class()
        engine = EngineCls(
            checkpoint=checkpoint,
            device=device,
            model_name=model_name,
            max_seq=int(max_seq),
            max_q_seq=int(max_q_seq),
        )
        return cls(engine)

    @property
    def fe(self) -> Any:
        return self._engine.fe

    def warmup(self, shapes: list[tuple[int, int]], **kwargs: Any) -> None:
        del kwargs
        if shapes:
            self._engine.warmup(shapes)

    def _stream_kwargs(self, req: ChatRequest) -> dict[str, Any]:
        extras = dict(req.extras)
        return {
            "messages": messages_from_request(req),
            "tools": req.tools,
            "max_tokens": int(req.max_tokens),
            "temperature": float(req.temperature),
            "top_p": float(req.top_p),
            "top_k": int(req.top_k),
            "seed": req.seed if req.seed is not None else extras.get("seed"),
            "stop": req.stop if req.stop is not None else extras.get("stop"),
        }

    async def _iter_events(self, req: ChatRequest) -> AsyncIterator[tuple[Any, ...]]:
        kw = self._stream_kwargs(req)
        async for ev in self._engine.stream_generate(**kw):
            yield ev

    async def chat_async(self, req: ChatRequest) -> ChatResult:
        content = ""
        tool_calls: list[dict[str, Any]] = []
        finish = "stop"
        usage: dict[str, Any] = {}
        async for ev in self._iter_events(req):
            if ev[0] == "content":
                content += ev[1]
            elif ev[0] == "tool_calls":
                tool_calls.extend(ev[1])
            elif ev[0] == "finish":
                _, finish, usage = ev
        return ChatResult(
            content=content or None,
            tool_calls=tool_calls,
            finish_reason=str(finish),
            usage=dict(usage),
            extensions=flashrt_extensions_from_usage(usage),
        )

    async def chat_stream_async(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        async for ev in self._iter_events(req):
            if ev[0] == "content":
                yield ChatChunk(content_delta=str(ev[1]))
            elif ev[0] == "tool_calls":
                yield ChatChunk(tool_calls=list(ev[1]))
            elif ev[0] == "finish":
                _, finish, usage = ev
                yield ChatChunk(
                    finish_reason=str(finish),
                    usage=dict(usage),
                )

    def register_routes(self, app: Any) -> None:
        del app
