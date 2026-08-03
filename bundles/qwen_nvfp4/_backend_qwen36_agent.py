"""Qwen3.6 backend — FlashRT ``serving/qwen36_agent`` only (no legacy server)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Iterator

from flashcli_bundle.openai_compat import (
    format_enable_thinking_resolved,
    resolve_enable_thinking,
    sse_lines_to_chat_chunks,
)
from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult
from _flashrt_qwen36_agent import import_qwen36_agent_modules

from _qwen36_thinking import Qwen36ThinkingStreamSplitter, enable_thinking_from_request
from _qwen_util import (
    agent_result_to_chat,
    chat_request_to_openai_body,
    usage_from_qwen36_engine,
)
from _serve_backend import bridge_sync_chunk_iterator

log = logging.getLogger(__name__)


class Qwen36AgentBackend:
    """Wraps ``AgentService`` + ``Qwen36FrontendAgentEngine``."""

    def __init__(self, service: Any, *, model_name: str, warmup_k: int) -> None:
        self._service = service
        self.model_name = model_name
        self._warmup_k = int(warmup_k)
        self._engine = service.engine

    @classmethod
    def from_checkpoint(
        cls,
        *,
        checkpoint: str,
        device: str,
        max_seq: int,
        model_name: str,
        K: int = 4,
        route_min_seq: int | None = 0,
        graph_cache_max: int | None = None,
        capsule_budget_bytes: int = 0,
        default_max_tokens: int = 2048,
        max_output_tokens: int = 16384,
    ) -> Qwen36AgentBackend:
        mods = import_qwen36_agent_modules()
        EngineCls = mods["Qwen36FrontendAgentEngine"]
        AgentService = mods["AgentService"]

        if graph_cache_max is None:
            graph_cache_max = _auto_graph_cache_max(max_seq)

        engine = EngineCls.from_checkpoint(
            checkpoint,
            device=device,
            max_seq=int(max_seq),
            model_name=model_name,
            route_min_seq=route_min_seq,
            graph_cache_max=graph_cache_max,
        )
        if not engine.spec_enabled:
            log.warning(
                "Qwen3.6 MTP head not loaded — speculative decode disabled. "
                "Set FLASHRT_QWEN36_MTP_CKPT_DIR to the paired MTP checkpoint."
            )
        service = AgentService(
            engine,
            capsule_budget_bytes=int(capsule_budget_bytes),
            default_k=int(K),
            default_max_tokens=int(default_max_tokens),
            max_output_tokens=int(max_output_tokens),
        )
        return cls(service, model_name=model_name, warmup_k=int(K))

    @property
    def fe(self) -> Any:
        return self._engine.fe

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        *,
        enable_thinking: bool = True,
    ) -> Any:
        import torch

        token_ids = self._engine.tokenize_chat(
            messages, tools=tools, enable_thinking=enable_thinking
        )
        prompt_len = len(token_ids)
        max_seq = int(getattr(self.fe, "_user_max_seq", 0) or self._engine.max_seq)
        if max_seq and prompt_len + int(max_tokens) > max_seq:
            raise ValueError(
                f"prompt + max_tokens = {prompt_len + int(max_tokens)} "
                f"exceeds max_seq {max_seq}"
            )
        return torch.tensor([token_ids], dtype=torch.long)

    def warmup(
        self,
        shapes: list[tuple[int, int]],
        *,
        committed_max_prompt: int = 1024,
        **kwargs: Any,
    ) -> None:
        del kwargs
        if not shapes:
            return
        warmed = self._engine.warmup_committed_stream(
            shapes,
            K=self._warmup_k,
            committed_max_prompt=int(committed_max_prompt),
            long_decode_graphs=True,
            long_prefill_graphs=False,
        )
        total_ms = sum(float(item.get("wall_ms", 0.0)) for item in warmed)
        log.info(
            "qwen36 agent warmup: %d shape(s), total_wall_ms=%.1f",
            len(warmed),
            total_ms,
        )

    def _agent_request(self, req: ChatRequest) -> Any:
        thinking_value, thinking_source = resolve_enable_thinking(
            dict(req.extras or {})
        )
        body = chat_request_to_openai_body(req)
        log.info(
            "qwen36 agent request | %s | forwarded=%s",
            format_enable_thinking_resolved(thinking_value, thinking_source),
            body.get("enable_thinking"),
        )
        return self._service.request_from_openai(body)

    async def chat_async(self, req: ChatRequest) -> ChatResult:
        agent_req = self._agent_request(req)
        result = await asyncio.to_thread(self._service.complete, agent_req)
        return agent_result_to_chat(
            result,
            route=getattr(self._engine, "_last_route", None),
            enable_thinking=enable_thinking_from_request(req),
        )

    def _iter_stream_chunks(self, req: ChatRequest) -> Iterator[ChatChunk]:
        thinking = enable_thinking_from_request(req)
        agent_req = self._agent_request(req)
        agent_req.stream = True
        t0 = time.perf_counter()
        first_delta_ms: float | None = None
        route = getattr(self._engine, "_last_route", None)
        splitter = Qwen36ThinkingStreamSplitter(enabled=thinking)

        for chunk in sse_lines_to_chat_chunks(
            self._service.stream_openai(agent_req, model=self.model_name)
        ):
            if chunk.content_delta:
                if first_delta_ms is None:
                    first_delta_ms = (time.perf_counter() - t0) * 1000.0
                for field, delta in splitter.feed(chunk.content_delta):
                    if field == "reasoning_content":
                        yield ChatChunk(reasoning_delta=delta)
                    else:
                        yield ChatChunk(content_delta=delta)
                continue
            if chunk.finish_reason:
                for field, delta in splitter.flush():
                    if field == "reasoning_content":
                        yield ChatChunk(reasoning_delta=delta)
                    else:
                        yield ChatChunk(content_delta=delta)
                raw_usage = dict(chunk.usage or {})
                timing: dict[str, Any] = {}
                for key in (
                    "prompt_tokens",
                    "completion_tokens",
                    "prefill_ms",
                    "first_delta_ms",
                    "ttft_ms",
                    "decode_ms",
                    "decode_tok_per_s",
                    "tok_per_s",
                    "e2e_tok_per_s",
                    "route",
                    "wall_s",
                ):
                    val = raw_usage.get(key)
                    if val is not None:
                        timing[key] = val
                # Client-observed TTFT only when AgentService did not report engine TTFT.
                if first_delta_ms is not None and timing.get("first_delta_ms") is None:
                    timing["first_delta_ms"] = first_delta_ms
                if route is not None and timing.get("route") is None:
                    timing["route"] = route
                cached = (raw_usage.get("prompt_tokens_details") or {}).get(
                    "cached_tokens"
                )
                if cached is not None:
                    timing["cached_tokens"] = int(cached)
                enriched = usage_from_qwen36_engine(
                    {k: v for k, v in timing.items() if v is not None}
                )
                for key in ("prompt_tokens_details",):
                    if key in raw_usage:
                        enriched[key] = raw_usage[key]
                yield ChatChunk(finish_reason=chunk.finish_reason, usage=enriched)
                continue
            yield chunk

    async def chat_stream_async(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        async for chunk in bridge_sync_chunk_iterator(
            lambda: self._iter_stream_chunks(req)
        ):
            yield chunk

    def register_routes(self, app: Any) -> None:
        from fastapi import HTTPException

        @app.post("/v1/sessions")
        async def create_session(raw: dict[str, Any] | None = None):
            raw = raw or {}
            rec = self._service.sessions.create(
                session_id=raw.get("session_id"),
                cache_salt=str(raw.get("cache_salt", "")),
                protected=bool(raw.get("protected", False)),
            )
            return {"session_id": rec.session_id}

        @app.delete("/v1/sessions/{session_id}")
        async def delete_session(session_id: str):
            deleted = self._service.sessions.delete(session_id)
            if not deleted:
                raise HTTPException(404, f"session not found: {session_id}")
            return {"deleted": True}


def _auto_graph_cache_max(max_seq: int) -> int:
    max_seq = int(max_seq)
    if max_seq <= 32768:
        return 1024
    if max_seq <= 131072:
        return 256
    return 128
