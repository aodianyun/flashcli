"""OpenAI-compat helpers used by bundle serve backends (no HTTP stack)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from flashcli_bundle.protocol import ChatChunk

DEFAULT_ENABLE_THINKING = True


def parse_bool_field(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return None


def format_enable_thinking_resolved(value: bool, source: str | None) -> str:
    """Log fragment after ``resolve_enable_thinking`` (source None → default)."""
    src = source if source else "default"
    return f"enable_thinking={str(value).lower()}(src={src})"


def resolve_enable_thinking(
    body: dict[str, Any],
    *,
    default: bool = DEFAULT_ENABLE_THINKING,
) -> tuple[bool, str | None]:
    if "enable_thinking" in body:
        parsed = parse_bool_field(body.get("enable_thinking"))
        if parsed is not None:
            return parsed, "body"
    kwargs = body.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and "enable_thinking" in kwargs:
        parsed = parse_bool_field(kwargs.get("enable_thinking"))
        if parsed is not None:
            return parsed, "chat_template_kwargs"
    return default, None


def apply_enable_thinking_to_openai_payload(payload: dict[str, Any]) -> bool:
    value, _ = resolve_enable_thinking(payload)
    payload["enable_thinking"] = value
    return value


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


def format_enable_thinking(body: dict[str, Any]) -> str:
    """Compact log fragment from the **client** body (call before payload injection)."""
    value, source = resolve_enable_thinking(body)
    return format_enable_thinking_resolved(value, source)


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


def summarize_chat_body(
    body: dict[str, Any],
    *,
    thinking_log: str | None = None,
) -> str:
    messages = body.get("messages")
    msg_part = (
        summarize_messages(messages)
        if isinstance(messages, list)
        else "messages=invalid"
    )
    stream = parse_bool_field(body.get("stream"))
    bits = [
        msg_part,
        f"max_tokens={body.get('max_tokens', 256)}",
        f"stream={stream if stream is not None else False}",
        f"temperature={body.get('temperature', 0.0)}",
    ]
    if body.get("tools"):
        bits.append(f"tools={len(body['tools'])}")
    if body.get("stop") is not None:
        bits.append(f"stop={body.get('stop')!r}")
    if body.get("seed") is not None:
        bits.append(f"seed={body.get('seed')}")
    bits.append(thinking_log if thinking_log else format_enable_thinking(body))
    return " | ".join(bits)


def sse_lines_to_chat_chunks(lines: Iterator[str]) -> Iterator[ChatChunk]:
    for line in lines:
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in obj:
            err = obj["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ValueError(msg or "stream error")
        choices = obj.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        finish = choice.get("finish_reason")
        usage = obj.get("usage")
        if delta.get("role"):
            continue
        if delta.get("reasoning_content"):
            yield ChatChunk(reasoning_delta=str(delta["reasoning_content"]))
        if "content" in delta and delta["content"]:
            yield ChatChunk(content_delta=str(delta["content"]))
        if delta.get("tool_calls"):
            yield ChatChunk(tool_calls=list(delta["tool_calls"]))
        if finish:
            yield ChatChunk(finish_reason=str(finish), usage=usage or None)
