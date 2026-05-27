"""Shared helpers for unified Qwen NVFP4 bundle (qwen3 + qwen36)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Iterator

from flashcli.bundle.activate import active_bundle
from flashcli.bundle.manifest import BundleManifest
from flashcli.bundle.variants import (
    resolve_bundle_variant,
    variant_merged_load_options,
    variant_serve_cfg,
)
from flashcli.engines.base import ChatChunk, ChatRequest, ChatResult


def resolve_model_variant(bundle: BundleManifest, options: dict[str, Any]) -> str:
    name = (
        options.get("model")
        or options.get("model_variant")
        or options.get("variant")
    )
    return resolve_bundle_variant(bundle, str(name) if name else None)


def serve_cfg(bundle: BundleManifest | None = None, variant: str | None = None) -> dict[str, Any]:
    b = bundle or active_bundle()
    if b is None:
        return {}
    key = resolve_bundle_variant(b, variant)
    return variant_serve_cfg(b, key)


def parse_warmup_spec(spec: str | None) -> list[tuple[int, int]]:
    if not spec or not str(spec).strip():
        return []
    shapes: list[tuple[int, int]] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        pl, mt = part.split(":", 1)
        shapes.append((int(pl), int(mt)))
    return shapes


def messages_from_request(req: ChatRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in req.messages:
        msg: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        out.append(msg)
    return out


def run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        raise RuntimeError(
            "Cannot run async Qwen engine from an active event loop; use serve mode."
        )
    return asyncio.run(coro)


def qwen36_result_to_chat(data: dict[str, Any]) -> ChatResult:
    finish = "tool_calls" if data.get("tool_calls") else "stop"
    return ChatResult(
        content=data.get("text") or None,
        tool_calls=list(data.get("tool_calls") or []),
        finish_reason=finish,
        usage={
            "prompt_tokens": data.get("prompt_tokens", 0),
            "completion_tokens": data.get("completion_tokens", 0),
            "total_tokens": int(data.get("prompt_tokens", 0))
            + int(data.get("completion_tokens", 0)),
            "wall_s": data.get("wall_s"),
            "tok_per_s": data.get("tok_per_s"),
        },
    )


async def collect_qwen3_stream(
    engine: Any,
    req: ChatRequest,
) -> ChatResult:
    messages = messages_from_request(req)
    content = ""
    tool_calls: list[dict[str, Any]] = []
    finish = "stop"
    usage: dict[str, Any] = {}
    async for ev in engine.stream_generate(
        messages,
        req.tools,
        req.max_tokens,
        req.temperature,
        req.top_p,
        req.top_k,
        req.seed,
        req.stop,
    ):
        if ev[0] == "content":
            content += ev[1]
        elif ev[0] == "tool_calls":
            tool_calls.extend(ev[1])
        elif ev[0] == "finish":
            _, finish, usage = ev
    return ChatResult(
        content=content or None,
        tool_calls=tool_calls,
        finish_reason=finish,
        usage=usage,
    )


async def iter_qwen3_stream(
    engine: Any,
    req: ChatRequest,
) -> AsyncIterator[ChatChunk]:
    messages = messages_from_request(req)
    async for ev in engine.stream_generate(
        messages,
        req.tools,
        req.max_tokens,
        req.temperature,
        req.top_p,
        req.top_k,
        req.seed,
        req.stop,
    ):
        if ev[0] == "content":
            yield ChatChunk(content_delta=ev[1])
        elif ev[0] == "tool_calls":
            yield ChatChunk(tool_calls=ev[1])
        elif ev[0] == "finish":
            _, finish, usage = ev
            yield ChatChunk(finish_reason=finish, usage=usage)


def chat_stream_sync(engine: Any, req: ChatRequest) -> Iterator[ChatChunk]:
    async def _gen() -> AsyncIterator[ChatChunk]:
        async for chunk in iter_qwen3_stream(engine, req):
            yield chunk

    async def _collect() -> list[ChatChunk]:
        return [c async for c in _gen()]

    for chunk in run_async(_collect()):
        yield chunk


def merge_load_options(
    bundle: BundleManifest,
    **options: Any,
) -> dict[str, Any]:
    variant = resolve_model_variant(bundle, options)
    merged = variant_merged_load_options(bundle, variant, **options)
    merged.setdefault("device", "cuda:0")
    merged.setdefault("max_seq", int(merged.get("max_seq", 2048)))
    if variant == "qwen3":
        merged.setdefault("max_q_seq", int(merged.get("max_q_seq", 128)))
    if variant == "qwen36":
        merged.setdefault("K", int(merged.get("K", 6)))
        if options.get("K") is not None:
            merged["K"] = int(options["K"])
    return merged
