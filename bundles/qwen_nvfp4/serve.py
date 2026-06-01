"""Unified Qwen NVFP4 ServeEngine — all variants use the same flashcli serve protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from flashcli.bundle.activate import active_bundle
from flashcli.engines.base import ChatChunk, ChatRequest, ChatResult
from flashcli.models.registry import Preset

from _backend_qwen3 import Qwen3Backend
from _backend_qwen36_agent import Qwen36AgentBackend
from _qwen_util import (
    merge_load_options,
    parse_warmup_spec,
    resolve_serve_warmup_spec,
    run_async,
    serve_cfg,
)
from _serve_backend import ServeChatBackend

_VARIANT_DEFAULTS: dict[str, dict[str, Any]] = {
    "qwen3": {
        "max_seq": 2048,
        "max_q_seq": 128,
        "warmup_preset": "auto",
    },
    "qwen36": {
        "max_seq": 262208,
        "K": 4,
        "warmup_preset": "agent",
        "default_max_tokens": 2048,
        "max_output_tokens": 8192,
        "warmup_committed_max_prompt": 1024,
    },
}


class ServeEngine:
    """Bundle entry for ``flashcli serve`` — delegates to a ``ServeChatBackend``."""

    def __init__(self) -> None:
        self._backend: ServeChatBackend | None = None
        self._variant: str = ""
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
        self._variant = str(opts.get("model_variant", "qwen3"))
        defaults = _VARIANT_DEFAULTS.get(self._variant, {})
        self._model_id = str(
            opts.get("model_name")
            or serve_cfg(bundle, self._variant).get("model_name")
            or self._variant
        )

        ckpt = str(checkpoint.expanduser().resolve())
        device = str(opts.get("device", "cuda:0"))

        if self._variant == "qwen36":
            self._backend = Qwen36AgentBackend.from_checkpoint(
                checkpoint=ckpt,
                device=device,
                max_seq=int(opts.get("max_seq", defaults.get("max_seq", 262208))),
                model_name=self._model_id,
                K=int(opts.get("K", defaults.get("K", 4))),
                route_min_seq=opts.get("route_min_seq", 0),
                capsule_budget_bytes=int(opts.get("capsule_budget_bytes", 0)),
                default_max_tokens=int(
                    opts.get("default_max_tokens", defaults.get("default_max_tokens", 2048))
                ),
                max_output_tokens=int(
                    opts.get("max_output_tokens", defaults.get("max_output_tokens", 8192))
                ),
            )
            return

        self._backend = Qwen3Backend.from_checkpoint(
            checkpoint=ckpt,
            device=device,
            model_name=self._model_id,
            max_seq=int(opts.get("max_seq", defaults.get("max_seq", 2048))),
            max_q_seq=int(opts.get("max_q_seq", defaults.get("max_q_seq", 128))),
        )

    def resolve_warmup(
        self,
        *,
        preset: str | None = None,
        extra_spec: str | None = None,
        bundle_default: str | None = None,
    ) -> str | None:
        defaults = _VARIANT_DEFAULTS.get(self._variant, {})
        max_seq = int(self._load_opts.get("max_seq", defaults.get("max_seq", 2048)))
        max_q_seq = int(self._load_opts.get("max_q_seq", defaults.get("max_q_seq", 128)))
        if self._variant == "qwen36":
            max_q_seq = 0
        preset = preset or str(
            self._load_opts.get("warmup_preset") or defaults.get("warmup_preset") or "auto"
        )
        return resolve_serve_warmup_spec(
            self._variant,
            preset=preset,
            max_seq=max_seq,
            max_q_seq=max_q_seq,
            extra_spec=extra_spec,
            bundle_default=bundle_default or serve_cfg(variant=self._variant).get("warmup"),
        )

    def warmup(self, spec: str | None) -> None:
        if self._backend is None:
            raise RuntimeError("ServeEngine.load() not called")
        shapes = parse_warmup_spec(spec)
        if not shapes:
            return
        if self._variant == "qwen36":
            assert isinstance(self._backend, Qwen36AgentBackend)
            self._backend.warmup(
                shapes,
                committed_max_prompt=int(
                    self._load_opts.get(
                        "warmup_committed_max_prompt",
                        _VARIANT_DEFAULTS["qwen36"]["warmup_committed_max_prompt"],
                    )
                ),
            )
            return
        self._backend.warmup(shapes)

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
