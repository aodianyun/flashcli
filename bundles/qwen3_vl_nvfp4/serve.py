"""Qwen3-VL NVFP4 ServeEngine."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import serve_option_defaults
from flashcli_bundle.preset import Preset
from flashcli_bundle.protocol import ChatChunk, ChatRequest, ChatResult

from _backend_qwen3_vl import Qwen3VlBackend
from _qwen3_vl_util import merge_load_options, resolve_warmup_tokens, run_async, vl_processor_fallback_repos
from _serve_backend import ServeChatBackend


class ServeEngine:
    def __init__(self) -> None:
        self._backend: ServeChatBackend | None = None
        self._model_id = ""
        self._load_opts: dict[str, Any] = {}

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
        self._load_opts = dict(opts)
        self._model_id = str(opts["model_name"])

        self._backend = Qwen3VlBackend.from_checkpoint(
            checkpoint=str(checkpoint.expanduser().resolve()),
            device=str(opts["device"]),
            model_name=self._model_id,
            max_seq=int(opts["max_seq"]),
            max_q_seq=int(opts.get("max_q_seq", 1024)),
            max_pixels=int(opts["max_pixels"]) if opts.get("max_pixels") is not None else None,
            processor_fallback_repos=vl_processor_fallback_repos(bundle),
        )

    def resolve_warmup(
        self,
        *,
        preset: str | None = None,
        extra_spec: str | None = None,
        bundle_default: str | None = None,
    ) -> str | None:
        n = resolve_warmup_tokens(
            preset=preset or str(self._load_opts.get("warmup_preset", "none")),
            extra_spec=extra_spec,
            bundle_default=bundle_default or serve_option_defaults(active_bundle() or {}).get("warmup"),
        )
        return str(n) if n > 0 else None

    def warmup(self, spec: str | None) -> None:
        if self._backend is None:
            raise RuntimeError("ServeEngine.load() not called")
        if not spec:
            return
        try:
            n = int(spec)
        except ValueError:
            return
        self._backend.warmup(max_new_tokens=n)

    async def chat_async(self, request: ChatRequest) -> ChatResult:
        if self._backend is None:
            raise RuntimeError("ServeEngine.load() not called")
        return await self._backend.chat_async(request)

    def chat(self, request: ChatRequest) -> ChatResult:
        return run_async(self.chat_async(request))

    async def chat_stream_async(
        self, request: ChatRequest
    ) -> AsyncIterator[ChatChunk]:
        if self._backend is None:
            raise RuntimeError("ServeEngine.load() not called")
        async for chunk in self._backend.chat_stream_async(request):
            yield chunk

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        async def _collect() -> list[ChatChunk]:
            return [c async for c in self.chat_stream_async(request)]

        for chunk in run_async(_collect()):
            yield chunk

    def register_routes(self, app: Any) -> None:
        if self._backend is not None:
            self._backend.register_routes(app)
