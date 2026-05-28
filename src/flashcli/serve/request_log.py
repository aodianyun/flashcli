"""Human-friendly HTTP request logging for flashcli serve."""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.requests import Request

log = logging.getLogger("flashcli.serve")

_SENSITIVE_HEADERS = frozenset(
    {"authorization", "x-api-key", "cookie", "set-cookie"}
)


def client_label(request: Request) -> str:
    if request.client:
        return f"{request.client.host}:{request.client.port}"
    return "unknown"


def header_hint(request: Request) -> str:
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


def _content_summary(content: Any) -> str:
    if content is None:
        return "empty"
    if isinstance(content, str):
        n = len(content)
        preview = _truncate(content, 72)
        return f"chars={n} preview={preview!r}"
    if isinstance(content, list):
        kinds: list[str] = []
        for part in content[:6]:
            if isinstance(part, dict):
                kinds.append(str(part.get("type", "part")))
            else:
                kinds.append(type(part).__name__)
        extra = f"+{len(content) - 6}" if len(content) > 6 else ""
        return f"parts={len(content)} types=[{','.join(kinds)}{extra}]"
    return f"type={type(content).__name__}"


def summarize_messages(messages: list[Any]) -> str:
    if not messages:
        return "messages=0"
    parts: list[str] = []
    for i, raw in enumerate(messages):
        if not isinstance(raw, dict):
            parts.append(f"{i}:?")
            continue
        role = str(raw.get("role", "?"))
        seg = f"{i}:{role}:{_content_summary(raw.get('content'))}"
        if raw.get("tool_calls"):
            seg += f" tool_calls={len(raw['tool_calls'])}"
        parts.append(seg)
    return f"messages={len(messages)} [" + "; ".join(parts) + "]"


def summarize_chat_body(body: dict[str, Any]) -> str:
    messages = body.get("messages")
    msg_part = (
        summarize_messages(messages)
        if isinstance(messages, list)
        else "messages=invalid"
    )
    bits = [
        msg_part,
        f"max_tokens={body.get('max_tokens', 256)}",
        f"stream={bool(body.get('stream', False))}",
        f"temperature={body.get('temperature', 0.0)}",
    ]
    if body.get("tools"):
        bits.append(f"tools={len(body['tools'])}")
    if body.get("stop") is not None:
        bits.append(f"stop={body.get('stop')!r}")
    if body.get("seed") is not None:
        bits.append(f"seed={body.get('seed')}")
    return " | ".join(bits)


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
