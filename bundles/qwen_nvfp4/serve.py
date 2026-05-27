"""Unified Qwen NVFP4 ServeEngine — ``--model qwen3|qwen36`` selects backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from flashcli.bundle.activate import active_bundle
from flashcli.engines.base import ChatChunk, ChatRequest, ChatResult
from flashcli.models.registry import Preset

from _qwen_util import (
    collect_qwen3_stream,
    iter_qwen3_stream,
    merge_load_options,
    messages_from_request,
    parse_warmup_spec,
    qwen36_result_to_chat,
    resolve_model_variant,
    run_async,
    serve_cfg,
)


class ServeEngine:
    def __init__(self) -> None:
        self._engine: Any = None
        self._variant: str = ""
        self._model_id = ""

    @property
    def model_id(self) -> str:
        return self._model_id

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        del preset
        bundle = active_bundle()
        if bundle is None:
            raise RuntimeError(
                "No active bundle; activate bundle runtime before ServeEngine.load()"
            )
        opts = merge_load_options(bundle, **options)
        self._variant = str(opts.get("model_variant", "qwen3"))
        self._model_id = str(opts.get("model_name") or serve_cfg(bundle, self._variant).get("model_name") or self._variant)

        ckpt = str(checkpoint.expanduser().resolve())
        device = str(opts.get("device", "cuda:0"))

        if self._variant == "qwen36":
            from _flashrt_serve import import_qwen36_engine_class

            EngineCls = import_qwen36_engine_class()
            self._engine = EngineCls(
                checkpoint=ckpt,
                K=int(opts.get("K", 6)),
                max_seq=int(opts.get("max_seq", 2048)),
                device=device,
                model_name=self._model_id,
            )
            return

        from _flashrt_serve import import_qwen3_engine_class

        EngineCls = import_qwen3_engine_class()
        self._engine = EngineCls(
            checkpoint=ckpt,
            device=device,
            model_name=self._model_id,
            max_seq=int(opts.get("max_seq", 2048)),
            max_q_seq=int(opts.get("max_q_seq", 128)),
        )

    def warmup(self, spec: str | None) -> None:
        if self._engine is None:
            raise RuntimeError("ServeEngine.load() not called")
        shapes = parse_warmup_spec(spec or serve_cfg(variant=self._variant).get("warmup"))
        if shapes:
            self._engine.warmup(shapes)

    async def chat_async(self, request: ChatRequest) -> ChatResult:
        if self._engine is None:
            raise RuntimeError("ServeEngine.load() not called")
        if self._variant == "qwen36":
            data = await self._engine.generate(
                messages_from_request(request),
                request.tools,
                request.max_tokens,
            )
            return qwen36_result_to_chat(data)
        return await collect_qwen3_stream(self._engine, request)

    def chat(self, request: ChatRequest) -> ChatResult:
        return run_async(self.chat_async(request))

    async def chat_stream_async(
        self, request: ChatRequest
    ) -> AsyncIterator[ChatChunk]:
        if self._engine is None:
            raise RuntimeError("ServeEngine.load() not called")
        if self._variant == "qwen36":
            result = await self.chat_async(request)
            if result.content:
                yield ChatChunk(content_delta=result.content)
            if result.tool_calls:
                yield ChatChunk(tool_calls=result.tool_calls)
            yield ChatChunk(finish_reason=result.finish_reason, usage=result.usage)
            return
        async for chunk in iter_qwen3_stream(self._engine, request):
            yield chunk

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        async def _collect() -> list[ChatChunk]:
            return [c async for c in self.chat_stream_async(request)]

        for chunk in run_async(_collect()):
            yield chunk
