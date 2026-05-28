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


def dedupe_warmup_shapes(shapes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for shape in shapes:
        if shape not in seen:
            out.append(shape)
            seen.add(shape)
    return out


def warmup_shapes_to_spec(shapes: list[tuple[int, int]]) -> str:
    return ",".join(f"{p}:{n}" for p, n in shapes)


def qwen36_warmup_preset_shapes(preset: str, max_seq: int) -> list[tuple[int, int]]:
    """Match FlashRT ``examples/qwen36_openai_server.py`` warmup buckets."""
    key = (preset or "auto").lower()
    if key in ("none", "off", "false", "0"):
        return []
    if key not in ("auto", "short", "long", "all"):
        raise ValueError(
            f"invalid warmup-preset {preset!r}; expected auto, short, long, all, or none"
        )
    short = [(8, 64), (128, 64), (512, 64), (1024, 64)]
    long = [
        (2048, 64),
        (4096, 64),
        (8192, 64),
        (16384, 64),
        (32768, 64),
        (65536, 64),
        (131072, 64),
        (204800, 64),
        (262144, 16),
    ]
    if key == "short":
        candidates = short
    elif key == "long":
        candidates = long
    else:
        candidates = short + long
    cap = int(max_seq)
    return [(p, n) for p, n in candidates if p + n <= cap]


def qwen3_warmup_preset_shapes(
    preset: str, max_seq: int, max_q_seq: int
) -> list[tuple[int, int]]:
    """Match FlashRT ``examples/qwen3_openai_server.py`` warmup buckets."""
    key = (preset or "auto").lower()
    if key in ("none", "off", "false", "0"):
        return []
    if key not in ("auto", "short", "all"):
        raise ValueError(
            f"invalid warmup-preset {preset!r}; expected auto, short, all, or none"
        )
    candidates = [
        (32, 128),
        (64, 128),
        (128, 256),
        (256, 256),
        (512, 256),
        (1024, 256),
    ]
    ms = int(max_seq)
    mq = int(max_q_seq)
    return [(p, n) for p, n in candidates if p <= mq and p + n <= ms]


def resolve_serve_warmup_spec(
    variant: str,
    *,
    preset: str | None,
    max_seq: int,
    max_q_seq: int,
    extra_spec: str | None,
    bundle_default: str | None,
) -> str | None:
    shapes: list[tuple[int, int]] = []
    if preset:
        if variant == "qwen36":
            shapes.extend(qwen36_warmup_preset_shapes(preset, max_seq))
        else:
            shapes.extend(qwen3_warmup_preset_shapes(preset, max_seq, max_q_seq))
    shapes.extend(parse_warmup_spec(extra_spec))
    shapes.extend(parse_warmup_spec(bundle_default))
    shapes = dedupe_warmup_shapes(shapes)
    return warmup_shapes_to_spec(shapes) if shapes else None


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
    """Run an async coroutine from sync code (``flashcli run``). No running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "Cannot run async Qwen engine from an active event loop; "
        "await chat_async() / chat_stream_async() instead."
    )


def usage_from_qwen36_engine(data: dict[str, Any]) -> dict[str, Any]:
    """Map FlashRT qwen36 ``generate()`` stats into OpenAI-style ``usage``.

    Qwen36 reports ``decode_tok_per_s`` / ``e2e_tok_per_s`` (not ``tok_per_s``).
    We expose both and set ``tok_per_s`` for bench/clients that expect qwen3 fields.
    """
    pt = int(data.get("prompt_tokens", 0) or 0)
    ct = int(data.get("completion_tokens", 0) or 0)
    decode_tps = data.get("decode_tok_per_s")
    e2e_tps = data.get("e2e_tok_per_s")
    tok = data.get("tok_per_s")
    if tok is None:
        if decode_tps is not None and float(decode_tps) > 0:
            tok = decode_tps
        elif e2e_tps is not None:
            tok = e2e_tps

    usage: dict[str, Any] = {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
    }
    for key in (
        "prefill_ms",
        "decode_ms",
        "wall_s",
        "decode_tok_per_s",
        "e2e_tok_per_s",
        "route",
    ):
        if data.get(key) is not None:
            usage[key] = data[key]
    if tok is not None:
        usage["tok_per_s"] = tok
    return usage


def qwen36_result_to_chat(data: dict[str, Any]) -> ChatResult:
    finish = "tool_calls" if data.get("tool_calls") else "stop"
    return ChatResult(
        content=data.get("text") or None,
        tool_calls=list(data.get("tool_calls") or []),
        finish_reason=finish,
        usage=usage_from_qwen36_engine(data),
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
    if options.get("max_seq") is not None:
        merged["max_seq"] = int(options["max_seq"])
    if options.get("max_q_seq") is not None:
        merged["max_q_seq"] = int(options["max_q_seq"])
    return merged
