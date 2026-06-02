"""Shared helpers for unified Qwen NVFP4 bundle (qwen3 + qwen36)."""

from __future__ import annotations

import asyncio
from typing import Any

from flashcli.bundle.activate import active_bundle
from flashcli.bundle.manifest import BundleManifest
from flashcli.bundle.variants import (
    resolve_bundle_variant,
    variant_merged_load_options,
    variant_serve_cfg,
)
from flashcli.engines.base import ChatRequest, ChatResult


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
    """Match FlashRT ``serving/qwen36_agent/server.py`` warmup buckets."""
    key = (preset or "auto").lower()
    if key in ("none", "off", "false", "0"):
        return []
    if key not in ("auto", "agent", "short", "long", "all"):
        raise ValueError(
            f"invalid warmup-preset {preset!r}; expected auto, agent, short, long, all, or none"
        )
    short = [(16, 128), (32, 128), (64, 128), (128, 128), (512, 128)]
    long = [
        (2048, 128),
        (8192, 128),
        (32768, 64),
        (131072, 64),
        (204800, 64),
        (262144, 16),
    ]
    if key == "short":
        candidates = short
    elif key == "long":
        candidates = long
    elif key == "all":
        candidates = short + [
            (1024, 128),
            (4096, 128),
            (16384, 128),
            (65536, 64),
        ] + long
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
    """Map FlashRT qwen36 stats into OpenAI-style ``usage``.

    Accepts legacy ``generate()`` dicts and agent ``AgentResult``-shaped dicts.
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
    cached = data.get("cached_tokens")
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": int(cached)}
    for key in (
        "prefill_ms",
        "decode_ms",
        "wall_s",
        "decode_tok_per_s",
        "e2e_tok_per_s",
        "route",
        "first_delta_ms",
        "session_id",
        "prefix_action",
    ):
        if data.get(key) is not None:
            usage[key] = data[key]
    if tok is not None:
        usage["tok_per_s"] = tok
    if data.get("ttft_ms") is not None:
        usage["ttft_ms"] = data.get("ttft_ms")
    elif data.get("first_delta_ms") is not None:
        usage["ttft_ms"] = data.get("first_delta_ms")
    elif data.get("prefill_ms") is not None:
        usage["ttft_ms"] = data.get("prefill_ms")
    return usage


def agent_result_to_dict(result: Any, *, route: str | None = None) -> dict[str, Any]:
    stats = result.stats
    out = {
        "text": result.text,
        "tool_calls": list(result.tool_calls or []),
        "prompt_tokens": int(stats.prompt_tokens),
        "completion_tokens": int(result.usage.get("completion_tokens", 0)),
        "cached_tokens": int(stats.cached_tokens),
        "prefill_ms": float(stats.prefill_ms),
        "first_delta_ms": float(stats.first_delta_ms),
        "decode_ms": float(stats.decode_ms),
        "decode_tok_per_s": float(stats.decode_tok_per_s),
        "session_id": result.session_id,
        "prefix_action": result.prefix_plan.action,
        "finish_reason": result.finish_reason,
    }
    if route is not None:
        out["route"] = route
    return out


def agent_result_to_chat(result: Any, *, route: str | None = None) -> ChatResult:
    data = agent_result_to_dict(result, route=route)
    stats = result.stats
    extensions = {
        "flashrt": {
            "session_id": result.session_id,
            "cached_tokens": int(stats.cached_tokens),
            "new_prefill_tokens": int(stats.new_prefill_tokens),
            "prefill_ms": float(stats.prefill_ms),
            "first_delta_ms": float(stats.first_delta_ms),
            "decode_ms": float(stats.decode_ms),
            "decode_tok_per_s": float(stats.decode_tok_per_s),
            "prefix_action": result.prefix_plan.action,
        }
    }
    return ChatResult(
        content=data.get("text") or None,
        tool_calls=list(data.get("tool_calls") or []),
        finish_reason=str(data.get("finish_reason") or "stop"),
        usage=usage_from_qwen36_engine(data),
        extensions=extensions,
    )


def chat_request_to_openai_body(req: ChatRequest) -> dict[str, Any]:
    """Build an OpenAI-shaped body for FlashRT ``request_from_openai`` helpers."""
    payload: dict[str, Any] = {
        "messages": messages_from_request(req),
        "max_tokens": int(req.max_tokens),
        "stream": bool(req.stream),
        "temperature": req.temperature,
        "top_p": req.top_p,
    }
    if req.tools:
        payload["tools"] = req.tools
    if req.stop:
        payload["stop"] = req.stop
    if req.seed is not None:
        payload["seed"] = req.seed
    payload.update(req.extras)
    return payload


def chat_request_to_agent_openai(req: ChatRequest) -> dict[str, Any]:
    return chat_request_to_openai_body(req)


def resolve_qwen36_route_min_seq(explicit: Any = None) -> int:
    """Short prompts should use ``short_spec`` (route when prompt < threshold).

    ``route_min_seq=0`` forces the long FP8-KV path for every request (~60 tok/s vs ~84).
    Default 512 matches ``FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ`` in comparable benches.
    """
    import os

    if explicit is not None:
        return int(explicit)
    env = os.environ.get("FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ", "").strip()
    if env.isdigit():
        return int(env)
    return 512


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
        merged.setdefault("K", int(merged.get("K", 4)))
        merged.setdefault("max_output_tokens", int(merged.get("max_output_tokens", 16384)))
        merged.setdefault("default_max_tokens", int(merged.get("default_max_tokens", 2048)))
        if options.get("K") is not None:
            merged["K"] = int(options["K"])
        if options.get("max_output_tokens") is not None:
            merged["max_output_tokens"] = int(options["max_output_tokens"])
        if options.get("default_max_tokens") is not None:
            merged["default_max_tokens"] = int(options["default_max_tokens"])
    if options.get("max_seq") is not None:
        merged["max_seq"] = int(options["max_seq"])
    if options.get("max_q_seq") is not None:
        merged["max_q_seq"] = int(options["max_q_seq"])
    return merged
