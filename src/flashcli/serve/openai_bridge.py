"""OpenAI chat-completions helpers shared by flashcli HTTP serve."""

from __future__ import annotations

import json
from typing import Any, Iterator

from flashcli.engines.base import ChatChunk, ChatMessage, ChatRequest, ChatResult

# Standard OpenAI chat/completions body keys (everything else → ChatRequest.extras).
_CHAT_COMPLETIONS_KNOWN: frozenset[str] = frozenset(
    {
        "messages",
        "model",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "top_k",
        "stream",
        "tools",
        "tool_choice",
        "stop",
        "seed",
        "n",
        "user",
        "response_format",
        "logprobs",
        "presence_penalty",
        "frequency_penalty",
    }
)


def parse_chat_completions_body(body: dict[str, Any]) -> ChatRequest:
    """Parse an OpenAI-style chat/completions JSON body into a generic ``ChatRequest``."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages required (non-empty list)")

    chat_messages = [
        ChatMessage(
            role=str(m.get("role", "user")),
            content=m.get("content"),
            tool_calls=m.get("tool_calls"),
        )
        for m in messages
        if isinstance(m, dict)
    ]
    if not chat_messages:
        raise ValueError("messages required (non-empty list)")

    stop = body.get("stop")
    if isinstance(stop, str):
        stop = [stop]

    raw_max = body.get("max_tokens")
    if raw_max is None:
        raw_max = body.get("max_completion_tokens")
    max_tokens = int(raw_max if raw_max is not None else 256)

    extras = {
        k: v
        for k, v in body.items()
        if k not in _CHAT_COMPLETIONS_KNOWN and v is not None
    }

    return ChatRequest(
        messages=chat_messages,
        max_tokens=max_tokens,
        temperature=float(body.get("temperature", 0.0)),
        top_p=float(body.get("top_p", 1.0)),
        top_k=int(body.get("top_k", 0)),
        stream=bool(body.get("stream", False)),
        tools=body.get("tools") if isinstance(body.get("tools"), list) else None,
        stop=stop if isinstance(stop, list) else None,
        seed=body.get("seed") if body.get("seed") is not None else None,
        extras=extras,
    )


def chat_result_to_completion_payload(
    result: ChatResult,
    *,
    completion_id: str,
    model_id: str,
    created: int,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": result.content,
    }
    if result.reasoning_content:
        msg["reasoning_content"] = result.reasoning_content
    if result.tool_calls:
        msg["tool_calls"] = result.tool_calls
    payload: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": result.finish_reason,
            }
        ],
        "usage": result.usage,
    }
    if result.extensions:
        payload.update(result.extensions)
    return payload


def sse_lines_to_chat_chunks(lines: Iterator[str]) -> Iterator[ChatChunk]:
    """Convert OpenAI SSE ``data: {...}`` lines into generic ``ChatChunk`` objects."""
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
