"""OpenAI chat-completions helpers shared by flashcli HTTP serve."""

from __future__ import annotations

from typing import Any, Iterator

from flashcli_bundle.openai_compat import parse_bool_field, sse_lines_to_chat_chunks
from flashcli_bundle.protocol import ChatChunk, ChatMessage, ChatRequest, ChatResult

__all__ = [
    "parse_chat_completions_body",
    "chat_result_to_completion_payload",
    "sse_lines_to_chat_chunks",
]

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
        stream=parse_bool_field(body.get("stream")) or False,
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
