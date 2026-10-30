"""Qwen3-VL backend — bundle ``ChatRequest`` / ``ChatResult`` adapter."""

from __future__ import annotations

from typing import Any, AsyncIterator

from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult

from _engine_qwen3_vl import Qwen3VlEngine
from _qwen3_vl_util import chat_request_to_frontend
from _serve_backend import ServeChatBackend, flashrt_extensions_from_usage


class Qwen3VlBackend:
    def __init__(self, engine: Qwen3VlEngine) -> None:
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
        max_pixels: int | None,
        processor_fallback_repos: tuple[str, ...] | None = None,
    ) -> Qwen3VlBackend:
        engine = Qwen3VlEngine(
            checkpoint=checkpoint,
            device=device,
            model_name=model_name,
            max_seq=int(max_seq),
            max_q_seq=int(max_q_seq),
            max_pixels=int(max_pixels) if max_pixels is not None else None,
            processor_fallback_repos=processor_fallback_repos,
        )
        return cls(engine)

    def warmup(self, max_new_tokens: int = 0, **kwargs: Any) -> None:
        del kwargs
        if max_new_tokens > 0:
            self._engine.warmup(max_new_tokens)

    def _stream_kwargs(self, req: ChatRequest) -> dict[str, Any]:
        extras = dict(req.extras)
        return {
            "messages": chat_request_to_frontend(req),
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
