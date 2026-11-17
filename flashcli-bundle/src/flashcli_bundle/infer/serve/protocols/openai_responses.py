"""Host-owned OpenAI Responses API (/v1/responses)."""

from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from flashcli_bundle.infer.engines.base import ChatMessage, ChatRequest, ChatResult
from flashcli_bundle.infer.serve.inference import GpuBusyError, InferenceGate
from flashcli_bundle.infer.serve.protocols.common import (
    chat_chunks,
    chat_once,
    new_id,
    now,
)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _content_parts(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise HTTPException(400, "content must be a string or array")
    parts: list[dict[str, Any]] = []
    text: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            raise HTTPException(400, "content parts must be objects")
        kind = str(item.get("type", "input_text"))
        if kind in ("input_text", "output_text", "text"):
            value = str(item.get("text", ""))
            text.append(value)
            parts.append({"type": "text", "text": value})
        elif kind == "input_image":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if not image_url:
                raise HTTPException(400, "input_image requires image_url")
            parts.append({"type": "image_url", "image_url": {"url": str(image_url)}})
        elif kind == "input_file":
            raise HTTPException(501, "input_file content is not implemented yet")
        else:
            raise HTTPException(400, f"unsupported content part type {kind!r}")
    if any(p.get("type") == "image_url" for p in parts):
        return parts
    return "".join(text)


def _tools(tools: Any) -> list[dict[str, Any]] | None:
    if not isinstance(tools, list) or not tools:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise HTTPException(400, "tools must be objects")
        if str(tool.get("type", "function")) != "function":
            raise HTTPException(400, f"unsupported tool type {tool.get('type')!r}")
        name = str(tool.get("name", ""))
        if not name:
            raise HTTPException(400, "function tool requires name")
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("parameters", {"type": "object"}),
                },
            }
        )
    return out


def _tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return choice
    kind = str(choice.get("type", ""))
    if kind == "function":
        return {"type": "function", "function": {"name": str(choice.get("name", ""))}}
    return choice


def _input_messages(value: Any) -> list[ChatMessage]:
    if isinstance(value, str):
        return [ChatMessage(role="user", content=value)]
    if not isinstance(value, list):
        raise HTTPException(400, "input must be a string or array")
    out: list[ChatMessage] = []
    for item in value:
        if not isinstance(item, dict):
            raise HTTPException(400, "input items must be objects")
        kind = str(item.get("type", "message"))
        if kind == "message":
            role = str(item.get("role", "user"))
            out.append(ChatMessage(role=role, content=_content_parts(item.get("content", ""))))
        elif kind == "function_call":
            name = str(item.get("name", ""))
            call_id = str(item.get("call_id", item.get("id", new_id("call"))))
            arguments = item.get("arguments", "")
            out.append(
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                        },
                    }],
                )
            )
        elif kind == "function_call_output":
            call_id = str(item.get("call_id", ""))
            if not call_id:
                raise HTTPException(400, "function_call_output requires call_id")
            output = item.get("output", "")
            out.append(ChatMessage(role="tool", content=str(output), tool_call_id=call_id))
        elif kind == "reasoning":
            summary = item.get("summary", [])
            text = "".join(
                str(part.get("text", ""))
                for part in summary
                if isinstance(part, dict)
            ) if isinstance(summary, list) else str(summary)
            out.append(ChatMessage(role="assistant", content="", reasoning_content=text))
        else:
            raise HTTPException(400, f"unsupported input item type {kind!r}")
    return out


def _request(body: dict[str, Any]) -> ChatRequest:
    messages: list[ChatMessage] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append(ChatMessage(role="system", content=instructions))
    messages.extend(_input_messages(body.get("input", "")))
    if not messages:
        raise HTTPException(400, "input required")
    if body.get("background"):
        raise HTTPException(501, "background responses are not implemented yet")
    if body.get("previous_response_id"):
        # The store is handled by the mounted route; this flag is resolved there.
        pass
    text = body.get("text")
    extras = {
        k: v
        for k, v in body.items()
        if k
        not in {
            "model", "input", "instructions", "max_output_tokens", "temperature",
            "top_p", "tools", "tool_choice", "stream", "metadata", "store",
            "previous_response_id", "reasoning", "text", "truncation", "user",
            "parallel_tool_calls", "background",
        }
        and v is not None
    }
    if isinstance(text, dict) and isinstance(text.get("format"), dict):
        extras["response_format"] = text["format"]
    choice = body.get("tool_choice")
    if choice is not None:
        extras["tool_choice"] = _tool_choice(choice)
    for key in ("reasoning", "truncation", "parallel_tool_calls"):
        if body.get(key) is not None:
            extras[key] = body[key]
    return ChatRequest(
        messages=messages,
        max_tokens=int(body.get("max_output_tokens", 1024) or 1024),
        temperature=float(body.get("temperature", 0.0) or 0.0),
        top_p=float(body.get("top_p", 1.0) or 1.0),
        stream=bool(body.get("stream")),
        tools=_tools(body.get("tools")),
        extras=extras,
    )


def _usage(result: ChatResult) -> dict[str, Any]:
    usage = result.usage or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def _output_items(result: ChatResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if result.reasoning_content:
        out.append({
            "id": new_id("rs"),
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": result.reasoning_content}],
        })
    if result.content:
        out.append({
            "id": new_id("msg"),
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": result.content, "annotations": []}],
        })
    for call in result.tool_calls or []:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        out.append({
            "id": new_id("fc"),
            "type": "function_call",
            "status": "completed",
            "call_id": str(call.get("id", new_id("call"))),
            "name": str(function.get("name", "")),
            "arguments": function.get("arguments", ""),
        })
    return out


def _response(
    result: ChatResult,
    *,
    response_id: str,
    model: str,
    created_at: int,
    previous_response_id: str | None,
    store: bool,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    incomplete = result.finish_reason == "length"
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "incomplete" if incomplete else "completed",
        "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
        "error": None,
        "model": model,
        "output": _output_items(result),
        "output_text": result.content or "",
        "previous_response_id": previous_response_id,
        "store": store,
        "metadata": metadata or {},
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "truncation": "disabled",
        "usage": _usage(result),
    }


def _conversation(req: ChatRequest, result: ChatResult) -> list[ChatMessage]:
    messages = list(req.messages)
    if result.content or result.tool_calls or result.reasoning_content:
        messages.append(
            ChatMessage(
                role="assistant",
                content=result.content or "",
                tool_calls=result.tool_calls,
                reasoning_content=result.reasoning_content,
            )
        )
    return messages


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[list[ChatMessage], dict[str, Any]]] = {}

    def get(self, response_id: str) -> tuple[list[ChatMessage], dict[str, Any]] | None:
        with self._lock:
            return self._items.get(response_id)

    def put(self, response_id: str, messages: list[ChatMessage], response: dict[str, Any]) -> None:
        with self._lock:
            self._items[response_id] = (messages, response)


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    store = _Store()

    @app.post("/v1/responses")
    async def responses(request: Request, body: dict[str, Any]):
        req = _request(body)
        previous_id = str(body.get("previous_response_id") or "") or None
        if previous_id:
            previous = store.get(previous_id)
            if previous is None:
                raise HTTPException(400, f"previous_response_id {previous_id!r} not found")
            req.messages = [*previous[0], *req.messages]
        store_enabled = body.get("store", True) is not False
        model = str(body.get("model") or engine.model_id)
        response_id = new_id("resp")
        created_at = now()
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
        if not req.stream:
            try:
                result = await chat_once(
                    gate, engine, request.headers.get("x-request-id", response_id), req
                )
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"inference failed: {exc}") from exc
            response = _response(
                result,
                response_id=response_id,
                model=model,
                created_at=created_at,
                previous_response_id=previous_id,
                store=store_enabled,
                metadata=metadata,
            )
            if store_enabled:
                store.put(response_id, _conversation(req, result), response)
            return response

        async def stream():
            try:
                await gate.acquire(request.headers.get("x-request-id", response_id))
            except GpuBusyError:
                yield _sse("response.failed", {"type": "response.failed", "response": {
                    "id": response_id, "object": "response", "status": "failed",
                    "error": {"code": "server_busy", "message": "GPU busy"},
                }})
                return
            shell = {
                "id": response_id, "object": "response", "created_at": created_at,
                "status": "in_progress", "model": model, "output": [],
                "output_text": "", "previous_response_id": previous_id,
                "store": store_enabled, "metadata": metadata or {},
            }
            text = ""
            reasoning = ""
            tool_calls: list[dict[str, Any]] = []
            try:
                yield _sse("response.created", {"type": "response.created", "response": shell})
                yield _sse("response.in_progress", {"type": "response.in_progress", "response": shell})
                output_index = 0
                text_index: int | None = None
                text_item_id = new_id("msg")
                reasoning_index: int | None = None
                reasoning_item_id = new_id("rs")
                async for chunk in chat_chunks(engine, req):
                    if chunk.reasoning_delta:
                        if reasoning_index is None:
                            reasoning_index = output_index
                            output_index += 1
                            shell["output"].append({
                                "id": reasoning_item_id, "type": "reasoning", "summary": [],
                            })
                            yield _sse("response.output_item.added", {
                                "type": "response.output_item.added",
                                "output_index": reasoning_index,
                                "item": shell["output"][-1],
                            })
                        reasoning += chunk.reasoning_delta
                        yield _sse("response.reasoning_summary_text.delta", {
                            "type": "response.reasoning_summary_text.delta",
                            "item_id": reasoning_item_id,
                            "output_index": reasoning_index,
                            "summary_index": 0,
                            "delta": chunk.reasoning_delta,
                        })
                    if chunk.content_delta:
                        if text_index is None:
                            if reasoning_index is not None:
                                yield _sse("response.reasoning_summary_text.done", {
                                    "type": "response.reasoning_summary_text.done",
                                    "item_id": reasoning_item_id,
                                    "output_index": reasoning_index,
                                    "summary_index": 0,
                                    "text": reasoning,
                                })
                                yield _sse("response.output_item.done", {
                                    "type": "response.output_item.done",
                                    "output_index": reasoning_index,
                                    "item": shell["output"][reasoning_index],
                                })
                            text_index = output_index
                            output_index += 1
                            item = {
                                "id": text_item_id, "type": "message", "status": "in_progress",
                                "role": "assistant", "content": [],
                            }
                            shell["output"].append(item)
                            yield _sse("response.output_item.added", {
                                "type": "response.output_item.added",
                                "output_index": text_index, "item": item,
                            })
                            yield _sse("response.content_part.added", {
                                "type": "response.content_part.added",
                                "item_id": text_item_id, "output_index": text_index,
                                "content_index": 0,
                                "part": {"type": "output_text", "text": "", "annotations": []},
                            })
                        text += chunk.content_delta
                        yield _sse("response.output_text.delta", {
                            "type": "response.output_text.delta",
                            "item_id": text_item_id,
                            "output_index": text_index,
                            "content_index": 0,
                            "delta": chunk.content_delta,
                        })
                    for call in chunk.tool_calls or []:
                        function = call.get("function") if isinstance(call, dict) else None
                        if not isinstance(function, dict):
                            continue
                        arguments = function.get("arguments", "")
                        item = {
                            "id": new_id("fc"), "type": "function_call", "status": "completed",
                            "call_id": str(call.get("id", new_id("call"))),
                            "name": str(function.get("name", "")), "arguments": arguments,
                        }
                        tool_calls.append(call)
                        idx = output_index
                        output_index += 1
                        shell["output"].append(item)
                        yield _sse("response.output_item.added", {
                            "type": "response.output_item.added",
                            "output_index": idx, "item": item,
                        })
                        yield _sse("response.function_call_arguments.done", {
                            "type": "response.function_call_arguments.done",
                            "item_id": item["id"], "output_index": idx,
                            "arguments": arguments,
                        })
                        yield _sse("response.output_item.done", {
                            "type": "response.output_item.done",
                            "output_index": idx, "item": item,
                        })
                    if chunk.finish_reason:
                        if text_index is not None:
                            shell["output"][text_index]["content"] = [{
                                "type": "output_text", "text": text, "annotations": [],
                            }]
                            yield _sse("response.output_text.done", {
                                "type": "response.output_text.done",
                                "item_id": text_item_id, "output_index": text_index,
                                "content_index": 0, "text": text,
                            })
                            yield _sse("response.content_part.done", {
                                "type": "response.content_part.done",
                                "item_id": text_item_id, "output_index": text_index,
                                "content_index": 0,
                                "part": {"type": "output_text", "text": text, "annotations": []},
                            })
                            shell["output"][text_index]["status"] = "completed"
                            yield _sse("response.output_item.done", {
                                "type": "response.output_item.done",
                                "output_index": text_index,
                                "item": shell["output"][text_index],
                            })
                        result = ChatResult(
                            content=text or None,
                            reasoning_content=reasoning or None,
                            tool_calls=tool_calls,
                            finish_reason=chunk.finish_reason,
                            usage=chunk.usage or {},
                        )
                        response = _response(
                            result, response_id=response_id, model=model,
                            created_at=created_at, previous_response_id=previous_id,
                            store=store_enabled, metadata=metadata,
                        )
                        response["output"] = shell["output"]
                        if store_enabled:
                            store.put(response_id, _conversation(req, result), response)
                        yield _sse("response.completed", {
                            "type": "response.completed", "response": response,
                        })
                        return
                yield _sse("response.completed", {
                    "type": "response.completed",
                    "response": {**shell, "status": "completed", "output_text": text},
                })
            except Exception as exc:
                yield _sse("response.failed", {
                    "type": "response.failed",
                    "response": {
                        "id": response_id, "object": "response", "status": "failed",
                        "error": {"code": "api_error", "message": str(exc)},
                    },
                })
            finally:
                gate.release()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
