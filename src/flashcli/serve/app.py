"""Unified OpenAI-compatible HTTP API for all ServeEngine implementations."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from flashcli.engines.base import ChatMessage, ChatRequest, ServeEngine


def build_app(engine: ServeEngine):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse

    app = FastAPI(title="flashcli unified serve")

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": engine.model_id}

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": engine.model_id,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "flashcli",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(body: dict[str, Any]):
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise HTTPException(400, "messages required")
        chat_messages = [
            ChatMessage(
                role=str(m.get("role", "user")),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
            )
            for m in messages
        ]
        stop = body.get("stop")
        if isinstance(stop, str):
            stop = [stop]
        req = ChatRequest(
            messages=chat_messages,
            max_tokens=int(body.get("max_tokens") or 256),
            temperature=float(body.get("temperature", 0.0)),
            top_p=float(body.get("top_p", 1.0)),
            top_k=int(body.get("top_k", 0)),
            stream=bool(body.get("stream", False)),
            tools=body.get("tools"),
            stop=stop if isinstance(stop, list) else None,
            seed=body.get("seed"),
        )
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        if not req.stream:
            result = engine.chat(req)
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": result.content,
            }
            if result.tool_calls:
                msg["tool_calls"] = result.tool_calls
            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": engine.model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": msg,
                        "finish_reason": result.finish_reason,
                    }
                ],
                "usage": result.usage,
            }

        def gen():
            first = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": engine.model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(first)}\n\n"
            for chunk in engine.chat_stream(req):
                if chunk.content_delta:
                    out = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": engine.model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": chunk.content_delta},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(out)}\n\n"
                for tc in chunk.tool_calls:
                    out = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": engine.model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"tool_calls": [tc]},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(out)}\n\n"
                if chunk.finish_reason:
                    last = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": engine.model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": chunk.finish_reason,
                            }
                        ],
                    }
                    if chunk.usage:
                        last["usage"] = chunk.usage
                    yield f"data: {json.dumps(last)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
