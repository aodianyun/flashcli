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
