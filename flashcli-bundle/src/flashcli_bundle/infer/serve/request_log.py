"""Human-friendly HTTP request logging for flashcli serve."""

from __future__ import annotations

import logging
import time
from typing import Any

from flashcli_bundle.openai_compat import (
    DEFAULT_ENABLE_THINKING,
    apply_enable_thinking_to_openai_payload,
    format_enable_thinking,
    format_enable_thinking_resolved,
    resolve_enable_thinking,
    summarize_chat_body,
    summarize_messages,
)

log = logging.getLogger("flashcli_bundle.infer.serve")

_SENSITIVE_HEADERS = frozenset(
    {"authorization", "x-api-key", "cookie", "set-cookie"}
)


def client_label(request: Any) -> str:
    if request.client:
        return f"{request.client.host}:{request.client.port}"
    return "unknown"


def header_hint(request: Any) -> str:
    parts: list[str] = []
    ua = request.headers.get("user-agent")
    if ua:
        parts.append(f"ua={_truncate(ua, 80)}")
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        parts.append(f"x-forwarded-for={fwd.split(',')[0].strip()}")
    req_id = request.headers.get("x-request-id")
    if req_id:
        parts.append(f"x-request-id={req_id}")
    return " ".join(parts)


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", "\\n").replace("\r", "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def usage_summary(usage: dict[str, Any] | None) -> str:
    if not usage:
        return ""
    keys = (
        "prompt_tokens",
        "completion_tokens",
        "prefill_ms",
        "decode_ms",
        "ttft_ms",
        "tok_per_s",
        "decode_tok_per_s",
        "route",
    )
    parts = [f"{k}={usage[k]}" for k in keys if usage.get(k) is not None]
    return " ".join(parts)


class RequestTimer:
    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


__all__ = [
    "DEFAULT_ENABLE_THINKING",
    "RequestTimer",
    "apply_enable_thinking_to_openai_payload",
    "client_label",
    "format_enable_thinking",
    "format_enable_thinking_resolved",
    "header_hint",
    "resolve_enable_thinking",
    "summarize_chat_body",
    "summarize_messages",
    "usage_summary",
]
