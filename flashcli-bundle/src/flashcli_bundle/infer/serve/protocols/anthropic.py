"""Host-owned Anthropic Messages API on top of the generic chat engine."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from flashcli_bundle.infer.engines.base import ChatChunk, ChatMessage, ChatRequest, ChatResult
from flashcli_bundle.infer.serve.inference import GpuBusyError, InferenceGate
from flashcli_bundle.infer.serve.protocols.common import (
    chat_chunks,
    chat_once,
    gpu_busy,
    new_id,
    now,
)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _text_from_blocks(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _image_part(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("type") == "base64":
        url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
    elif source.get("type") == "url":
        url = str(source.get("url", ""))
    else:
        return None
    if not url:
        return None
    return {"type": "image_url", "image_url": {"url": url}}


def _message_from_blocks(role: str, content: Any) -> list[ChatMessage]:
    if isinstance(content, str):
        return [ChatMessage(role=role, content=content)]
    if not isinstance(content, list):
        raise HTTPException(400, "message content must be a string or array of blocks")

    out: list[ChatMessage] = []
    text_parts: list[str] = []
    content_parts: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    reasoning: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            raise HTTPException(400, "message content blocks must be objects")
        kind = str(block.get("type", "text"))
        if kind == "text":
            text = str(block.get("text", ""))
            text_parts.append(text)
            content_parts.append({"type": "text", "text": text})
        elif kind == "image":
            part = _image_part(block)
            if part is None:
                raise HTTPException(400, "image block requires base64 or url source")
            content_parts.append(part)
        elif kind == "tool_use":
            name = str(block.get("name", ""))
            if not name:
                raise HTTPException(400, "tool_use block requires name")
            tool_calls.append(
                {
                    "id": str(block.get("id", new_id("call"))),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                }
            )
        elif kind == "tool_result":
            tool_call_id = str(block.get("tool_use_id", ""))
            if not tool_call_id:
                raise HTTPException(400, "tool_result block requires tool_use_id")
            result_text = _text_from_blocks(block.get("content"))
            if block.get("is_error"):
                result_text = f"Error: {result_text}"
            out.append(
                ChatMessage(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call_id,
                )
            )
        elif kind in ("thinking", "redacted_thinking"):
            thinking = str(block.get("thinking") or block.get("data") or "")
            if thinking:
                reasoning.append(thinking)
        elif kind == "document":
            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            text = str(source.get("data") or source.get("url") or "")
            if text:
                text_parts.append(text)
                content_parts.append({"type": "text", "text": text})
        else:
            raise HTTPException(400, f"unsupported content block type {kind!r}")

    if text_parts or content_parts:
        if role == "user" and any(p.get("type") == "image_url" for p in content_parts):
            content_value: Any = content_parts
        else:
            content_value = "".join(text_parts)
        out.insert(
            0,
            ChatMessage(
                role=role,
                content=content_value,
                tool_calls=tool_calls or None,
                reasoning_content="\n".join(reasoning) or None,
            ),
        )
    elif tool_calls or reasoning:
        out.insert(
            0,
            ChatMessage(
                role=role,
                content="",
                tool_calls=tool_calls or None,
                reasoning_content="\n".join(reasoning) or None,
            ),
        )
    if not out:
        out.append(ChatMessage(role=role, content=""))
    return out


def _tools(tools: Any) -> list[dict[str, Any]] | None:
    if not isinstance(tools, list) or not tools:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise HTTPException(400, "tools must be objects")
        name = str(tool.get("name", ""))
        if not name:
            raise HTTPException(400, "tool requires name")
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("input_schema", {"type": "object"}),
                },
            }
        )
    return out


def _tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return choice
    kind = str(choice.get("type", ""))
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool":
        return {"type": "function", "function": {"name": str(choice.get("name", ""))}}
    return choice


def _request(body: dict[str, Any]) -> ChatRequest:
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise HTTPException(400, "messages required (non-empty list)")
    messages: list[ChatMessage] = []
    system = body.get("system")
    if system:
        system_text = _text_from_blocks(system)
        if system_text:
            messages.append(ChatMessage(role="system", content=system_text))
    for item in raw_messages:
        if not isinstance(item, dict):
            raise HTTPException(400, "messages must be objects")
        role = str(item.get("role", "user"))
        messages.extend(_message_from_blocks(role, item.get("content")))
    if not messages:
        raise HTTPException(400, "messages required (non-empty list)")

    stop = body.get("stop_sequences")
    if isinstance(stop, str):
        stop = [stop]
    extras = {
        k: v
        for k, v in body.items()
        if k
        not in {
            "model", "messages", "system", "max_tokens", "temperature", "top_p",
            "top_k", "stop_sequences", "stream", "tools", "tool_choice",
        }
        and v is not None
    }
    choice = body.get("tool_choice")
    if choice is not None:
        extras["tool_choice"] = _tool_choice(choice)
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        extras["anthropic_thinking"] = thinking
        extras.setdefault("enable_thinking", thinking.get("type") != "disabled")
    return ChatRequest(
        messages=messages,
        max_tokens=int(body.get("max_tokens", 1024) or 1024),
        temperature=float(body.get("temperature", 0.0) or 0.0),
        top_p=float(body.get("top_p", 1.0) or 1.0),
        top_k=int(body.get("top_k", 0) or 0),
        stream=bool(body.get("stream")),
        tools=_tools(body.get("tools")),
        stop=stop if isinstance(stop, list) else None,
        extras=extras,
    )


def _stop_reason(reason: str | None) -> str | None:
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "tool_use": "tool_use",
        "stop_sequence": "stop_sequence",
        "content_filter": "refusal",
    }.get(reason or "", reason or "end_turn")


def _usage(result: ChatResult) -> dict[str, int]:
    usage = result.usage or {}
    return {
        "input_tokens": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
        "output_tokens": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
    }


def _content_blocks(result: ChatResult) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if result.reasoning_content:
        blocks.append({"type": "thinking", "thinking": result.reasoning_content, "signature": ""})
    if result.content:
        blocks.append({"type": "text", "text": result.content})
    for call in result.tool_calls or []:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        raw_input = function.get("arguments", {})
        try:
            tool_input = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
        except json.JSONDecodeError:
            tool_input = {}
        blocks.append(
            {
                "type": "tool_use",
                "id": str(call.get("id", new_id("toolu"))),
                "name": str(function.get("name", "")),
                "input": tool_input if isinstance(tool_input, dict) else {},
            }
        )
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return blocks


def _message(result: ChatResult, *, model: str, message_id: str, created: int) -> dict[str, Any]:
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": _content_blocks(result),
        "stop_reason": _stop_reason(result.finish_reason),
        "stop_sequence": None,
        "usage": _usage(result),
    }


def mount_messages(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.post("/v1/messages")
    async def messages(request: Request, body: dict[str, Any]):
        req = _request(body)
        model = str(body.get("model") or engine.model_id)
        message_id = new_id("msg")
        created = now()
        if not req.stream:
            try:
                result = await chat_once(
                    gate, engine, request.headers.get("x-request-id", message_id), req
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"inference failed: {exc}") from exc
            return _message(result, model=model, message_id=message_id, created=created)

        async def stream():
            usage = {"input_tokens": 0, "output_tokens": 0}
            block_index = -1
            block_open = False
            block_kind: str | None = None
            try:
                await gate.acquire(request.headers.get("x-request-id", message_id))
            except GpuBusyError:
                yield _sse(
                    "error",
                    {"type": "error", "error": {"type": "overloaded_error", "message": "GPU busy"}},
                )
                return
            try:
                yield _sse(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": message_id,
                            "type": "message",
                            "role": "assistant",
                            "model": model,
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": usage,
                        },
                    },
                )

                async def close_block() -> str | None:
                    nonlocal block_open, block_kind
                    if not block_open:
                        return None
                    block_open = False
                    kind = block_kind
                    block_kind = None
                    return _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})

                async for chunk in chat_chunks(engine, req):
                    if chunk.usage:
                        usage = {
                            "input_tokens": int(
                                chunk.usage.get("prompt_tokens", usage["input_tokens"]) or 0
                            ),
                            "output_tokens": int(
                                chunk.usage.get("completion_tokens", usage["output_tokens"]) or 0
                            ),
                        }
                    if chunk.reasoning_delta:
                        if not block_open or block_kind != "thinking":
                            if block_open:
                                yield await close_block()
                            block_index += 1
                            block_open = True
                            block_kind = "thinking"
                            yield _sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": block_index,
                                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                                },
                            )
                        yield _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": block_index,
                                "delta": {"type": "thinking_delta", "thinking": chunk.reasoning_delta},
                            },
                        )
                    if chunk.content_delta:
                        if not block_open or block_kind != "text":
                            if block_open:
                                yield await close_block()
                            block_index += 1
                            block_open = True
                            block_kind = "text"
                            yield _sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": block_index,
                                    "content_block": {"type": "text", "text": ""},
                                },
                            )
                        yield _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": block_index,
                                "delta": {"type": "text_delta", "text": chunk.content_delta},
                            },
                        )
                    for call in chunk.tool_calls or []:
                        if block_open:
                            yield await close_block()
                        function = call.get("function") if isinstance(call, dict) else None
                        if not isinstance(function, dict):
                            continue
                        raw_input = function.get("arguments", "")
                        try:
                            tool_input = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
                        except json.JSONDecodeError:
                            tool_input = {}
                        block_index += 1
                        yield _sse(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": block_index,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": str(call.get("id", new_id("toolu"))),
                                    "name": str(function.get("name", "")),
                                    "input": {},
                                },
                            },
                        )
                        yield _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": block_index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": json.dumps(tool_input, ensure_ascii=False),
                                },
                            },
                        )
                        yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                    if chunk.finish_reason:
                        if block_open:
                            yield await close_block()
                        yield _sse(
                            "message_delta",
                            {
                                "type": "message_delta",
                                "delta": {
                                    "stop_reason": _stop_reason(chunk.finish_reason),
                                    "stop_sequence": None,
                                },
                                "usage": usage,
                            },
                        )
                        yield _sse("message_stop", {"type": "message_stop"})
                        return
                if block_open:
                    yield await close_block()
                yield _sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": usage,
                    },
                )
                yield _sse("message_stop", {"type": "message_stop"})
            except Exception as exc:
                yield _sse(
                    "error",
                    {"type": "error", "error": {"type": "api_error", "message": str(exc)}},
                )
            finally:
                gate.release()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )


def _model_object(model: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "type": "model",
        "id": model,
        "display_name": model,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def mount_models(app: FastAPI, engine: Any) -> None:
    @app.get("/v1/models/{model_id}")
    async def model(model_id: str):
        if model_id != engine.model_id:
            return JSONResponse(
                status_code=404,
                content={
                    "type": "error",
                    "error": {"type": "not_found_error", "message": f"model {model_id!r} not found"},
                },
            )
        return _model_object(engine.model_id)


def mount_count_tokens(app: FastAPI, engine: Any) -> None:
    @app.post("/v1/messages/count_tokens")
    async def count_tokens(body: dict[str, Any]):
        req = _request(body)
        counter = getattr(engine, "count_tokens", None)
        if counter is None:
            return JSONResponse(
                status_code=501,
                content={
                    "type": "error",
                    "error": {
                        "type": "not_implemented_error",
                        "message": "the bundle does not expose count_tokens",
                    },
                },
            )
        try:
            value = counter(req)
            if hasattr(value, "__await__"):
                value = await value
            return {"input_tokens": int(value)}
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"type": "error", "error": {"type": "api_error", "message": str(exc)}},
            )
