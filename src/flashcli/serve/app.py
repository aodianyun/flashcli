"""Unified OpenAI-compatible HTTP API for all ServeEngine implementations."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from flashcli.engines.base import ChatMessage, ChatRequest, ServeEngine
from flashcli.serve.inference import GpuBusyError, InferenceGate, iter_on_inference_loop
from flashcli.serve.request_log import (
    RequestTimer,
    client_label,
    header_hint,
    log,
    summarize_chat_body,
    usage_summary,
)


def _gpu_busy_response(model_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": {
                "message": (
                    "GPU inference slot is busy: another chat completion is "
                    "running. This server processes one inference request at a "
                    "time (batch=1). Retry after the current request finishes."
                ),
                "type": "server_busy",
                "code": "gpu_busy",
                "model": model_id,
            }
        },
        headers={"Retry-After": "5"},
    )


def build_app(engine: ServeEngine) -> FastAPI:
    gate = InferenceGate()
    app = FastAPI(title="flashcli unified serve")

    class AccessLogMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path in ("/health", "/v1/models"):
                return await call_next(request)

            req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
            request.state.request_id = req_id
            timer = RequestTimer()
            request.state.timer = timer
            client = client_label(request)
            extra = header_hint(request)
            log.info(
                "→ %s %s | id=%s | from=%s | model=%s%s",
                request.method,
                request.url.path,
                req_id,
                client,
                engine.model_id,
                f" | {extra}" if extra else "",
            )
            try:
                response = await call_next(request)
                log.info(
                    "← %s %s | id=%s | from=%s | status=%s | %.1f ms",
                    request.method,
                    request.url.path,
                    req_id,
                    client,
                    response.status_code,
                    timer.elapsed_ms,
                )
                return response
            except HTTPException as exc:
                log.warning(
                    "← %s %s | id=%s | from=%s | status=%s | %.1f ms | %s",
                    request.method,
                    request.url.path,
                    req_id,
                    client,
                    exc.status_code,
                    timer.elapsed_ms,
                    exc.detail,
                )
                raise
            except Exception:
                log.exception(
                    "← %s %s | id=%s | from=%s | failed | %.1f ms",
                    request.method,
                    request.url.path,
                    req_id,
                    client,
                    timer.elapsed_ms,
                )
                raise

    app.add_middleware(AccessLogMiddleware)

    @app.get("/health")
    async def health():
        busy = gate.is_busy
        payload: dict[str, Any] = {
            "status": "ok",
            "model": engine.model_id,
            "inference_busy": busy,
        }
        if busy and gate.busy_holder:
            payload["inference_holder"] = gate.busy_holder
        return payload

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

    def _parse_chat_request(body: dict[str, Any]) -> ChatRequest:
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
        return ChatRequest(
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

    async def _chat_result(req: ChatRequest) -> Any:
        if hasattr(engine, "chat_async"):
            return await engine.chat_async(req)
        return engine.chat(req)

    async def _chunk_iter(req: ChatRequest):
        if hasattr(engine, "chat_stream_async"):
            async for chunk in engine.chat_stream_async(req):
                yield chunk
            return

        async def _sync_bridge():
            for chunk in engine.chat_stream(req):
                yield chunk

        async for chunk in _sync_bridge():
            yield chunk

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, body: dict[str, Any]):
        req_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
        timer: RequestTimer = getattr(request.state, "timer", None) or RequestTimer()
        client = client_label(request)
        summary = summarize_chat_body(body)

        log.info(
            "chat START | id=%s | from=%s | model=%s | %s",
            req_id,
            client,
            engine.model_id,
            summary,
        )

        try:
            req = _parse_chat_request(body)
        except HTTPException:
            log.warning(
                "chat END | id=%s | from=%s | status=400 | %.1f ms | invalid body",
                req_id,
                client,
                timer.elapsed_ms,
            )
            raise

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        if not req.stream:
            try:
                result = await gate.run(req_id, _chat_result(req))
            except GpuBusyError:
                log.warning(
                    "chat END | id=%s | from=%s | status=503 gpu_busy | %.1f ms | %s",
                    req_id,
                    client,
                    timer.elapsed_ms,
                    summary,
                )
                raise _gpu_busy_response(engine.model_id) from None
            except ValueError as exc:
                log.warning(
                    "chat END | id=%s | from=%s | status=400 | %.1f ms | %s",
                    req_id,
                    client,
                    timer.elapsed_ms,
                    exc,
                )
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:
                log.exception(
                    "chat END | id=%s | from=%s | status=500 | %.1f ms",
                    req_id,
                    client,
                    timer.elapsed_ms,
                )
                raise HTTPException(500, f"inference failed: {exc}") from exc

            msg: dict[str, Any] = {
                "role": "assistant",
                "content": result.content,
            }
            if result.tool_calls:
                msg["tool_calls"] = result.tool_calls
            usage_line = usage_summary(result.usage)
            log.info(
                "chat END | id=%s | from=%s | status=200 | %.1f ms | "
                "finish=%s | %s%s",
                req_id,
                client,
                timer.elapsed_ms,
                result.finish_reason,
                usage_line,
                f" | {summary}" if not usage_line else "",
            )
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

        try:
            await gate.acquire(req_id)
        except GpuBusyError:
            log.warning(
                "chat END | id=%s | from=%s | status=503 gpu_busy | %.1f ms | %s",
                req_id,
                client,
                timer.elapsed_ms,
                summary,
            )
            raise _gpu_busy_response(engine.model_id) from None

        async def stream_chunks():
            end_logged = False
            finish_label: str | None = None
            usage_line = ""

            def _log_chat_end(status: str, *, use_warning: bool = False) -> None:
                nonlocal end_logged
                if end_logged:
                    return
                end_logged = True
                parts = [
                    f"chat END | id={req_id}",
                    f"from={client}",
                    f"status={status}",
                    f"{timer.elapsed_ms:.1f} ms",
                ]
                if finish_label:
                    parts.append(f"finish={finish_label}")
                if usage_line:
                    parts.append(usage_line)
                msg = " | ".join(parts)
                if use_warning:
                    log.warning(msg)
                else:
                    log.info(msg)

            try:
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

                async for chunk in iter_on_inference_loop(
                    lambda: _chunk_iter(req),
                ):
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
                        finish_label = chunk.finish_reason
                        usage_line = usage_summary(chunk.usage)
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
                        _log_chat_end("200 stream")
                        return
                _log_chat_end(
                    "200 stream no_finish_chunk",
                    use_warning=True,
                )
            except ValueError as exc:
                _log_chat_end(f"400 stream | {exc}", use_warning=True)
                err = {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_request_error",
                        "code": "invalid_request",
                    }
                }
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                _log_chat_end(f"500 stream | {exc}", use_warning=True)
                log.exception(
                    "chat stream error | id=%s | from=%s | %.1f ms",
                    req_id,
                    client,
                    timer.elapsed_ms,
                )
                err = {
                    "error": {
                        "message": f"inference failed: {exc}",
                        "type": "server_error",
                        "code": "inference_failed",
                    }
                }
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                if not end_logged:
                    _log_chat_end(
                        "stream closed before finish (client disconnect or "
                        "proxy timeout)",
                        use_warning=True,
                    )
                gate.release()

        return StreamingResponse(stream_chunks(), media_type="text/event-stream")

    return app
